import sys
sys.path.append('../')
import torch
import torch.nn as nn
import torchaudio
from transformers import AutoFeatureExtractor, AutoModel
import numpy as np
import math

import os


def resolution_transformation(content, target_len, target_dim=None):
    """
    Transform the resolution of the input content to match the target length.

    Args:
        content: torch.tensor, shape (batch_size, source_len, dim)
        target_len: int, target length
        target_dim: int, target dimension (optional)

    Returns:
        mapped_feature: torch.tensor, shape (batch_size, target_len, dim)
    """
    batch_size, source_len, width = content.shape
    if target_dim is not None:
        width = target_dim
    content_4d = content.unsqueeze(1)
    mapped_feature_tensor = torch.nn.functional.interpolate(
        content_4d, size=(target_len, width), mode='bilinear', align_corners=False
    )
    mapped_feature_tensor = mapped_feature_tensor.squeeze(1)
    return mapped_feature_tensor

class SemanticLoss(nn.Module):
    def __init__(self, device='cuda', input_sr=44100):
        super(SemanticLoss, self).__init__()
        self.device = device

        # Initialize the semantic components
        self.semantic_feature_extractor = AutoFeatureExtractor.from_pretrained(
            "pretrained/w2v-bert-2.0"
            # "facebook/w2v-bert-2.0"
        )
        self.semantic_model = AutoModel.from_pretrained(
            "pretrained/w2v-bert-2.0"
            # "facebook/w2v-bert-2.0"
        )
        self.semantic_model.to(self.device)
        self.semantic_model.eval()

        self.resampler = torchaudio.transforms.Resample(orig_freq=input_sr, new_freq=16000).to(self.device)

    def extract_and_resize_embeddings(self, clean_audios, target_len, target_dim):
        """
        Extracts semantic embeddings from clean audios and resizes them to match target length and dimension.

        Args:
            clean_audios: Original clean audios, shape [batch_size, 1, audio_len]
            target_len: Target length to resize the embeddings to
            target_dim: Target dimension to resize the embeddings to

        Returns:
            resized_embeddings: Resized semantic embeddings, shape [batch_size, target_len, target_dim]
        """
        batch_size = clean_audios.shape[0]

        # Resample clean_audios to 16kHz
        clean_audios_16k = self.resampler(clean_audios)  # [batch_size, 1, seq_len_16k]
        clean_audios_16k = clean_audios_16k.cpu()
        # print("CLEAN_AUDIOS_16K", clean_audios_16k.shape)

        # Get input_features from the feature extractor
        with torch.no_grad():
            # input_features = torch.cat([
            #     self.semantic_feature_extractor(audio, sampling_rate=16000, return_tensors='pt', padding=True)['input_features']
            #     for audio in clean_audios_16k
            # ], dim=0)  # [batch_size, 136, 160]
            input_features = self.semantic_feature_extractor(
                [audio.squeeze(0).numpy() for audio in clean_audios_16k],
                sampling_rate=16000,
                return_tensors='pt',
                padding=True
            )['input_features']
            # print("INPUT FEATURES", input_features.shape)

            # Pass through semantic_model to get hidden states
            outputs = self.semantic_model(input_features=input_features.to(self.device), output_hidden_states=True)
            semantic_features = outputs.hidden_states[17]  # [batch_size, 136, 1024]

        # Resize semantic_features to match target_len and target_dim
        resized_embeddings = resolution_transformation(semantic_features, target_len=target_len, target_dim=target_dim)

        return resized_embeddings

    def forward(self, clean_audios, audio_embeds):
        """
        Computes the combined loss.

        Args:
            clean_audios: Original clean audios, shape [batch_size, 1, audio_len]
            audio_embeds: Audio embeddings from the model, shape [batch_size, seq_len_total, dim]
            rand_prompt: Boolean tensor indicating samples with prompts, shape [batch_size]
            prompt_len: Length of the prompt in tokens

        Returns:
            encoder_loss: Computed encoder loss scalar
        """
        batch_size = clean_audios.shape[0]

        # Resample clean_audios to 16kHz
        clean_audios_16k = self.resampler(clean_audios) # [batch_size, 1, seq_len_16k]
        clean_audios_16k = clean_audios_16k.cpu()
        # print("[LOSS] CLEAN_AUDIOS_16K", clean_audios_16k.shape)

        # Get input_features
        with torch.no_grad():
            # input_features = torch.cat([
            #     self.semantic_feature_extractor(audio, sampling_rate=16000, return_tensors='pt', padding=True)['input_features']
            #     for audio in clean_audios_16k
            # ], dim=0) # [batch_size, 136, 160] (80 band mel * 2)
            input_features = self.semantic_feature_extractor(
                [audio.squeeze(0).numpy() for audio in clean_audios_16k],
                sampling_rate=16000,
                return_tensors='pt',
                padding=True
            )['input_features']
            # print("[LOSS] INPUT FEATURES", input_features.shape)

            # Pass through semantic_model
            outputs = self.semantic_model(input_features=input_features.to(self.device), output_hidden_states=True)
            semantic_features = outputs.hidden_states[17] # [batch_size, 136, 1024]

        # Resize semantic_features to match audio_embeds
        semantic_features = resolution_transformation(
            semantic_features, target_len=audio_embeds.shape[1], target_dim=audio_embeds.shape[2]
        )

        # # Compute loss per position
        # feature_loss = torch.nn.functional.feature_loss(
        #     semantic_features, audio_embeds, reduction='none'
        # )  # [batch_size, seq_len_total, dim]
        # feature_loss = feature_loss.mean(dim=-1)  # [batch_size, seq_len_total]
        feature_loss = 1.0 - torch.nn.functional.cosine_similarity(
            semantic_features, audio_embeds, dim=-1
        )  # [batch_size, seq_len_total]

        # Create loss mask
        loss_mask = torch.ones_like(feature_loss, device=self.device)

        # Compute encoder_loss
        masked_feature_loss = feature_loss * loss_mask  # [batch_size, seq_len_total]
        encoder_loss = masked_feature_loss.sum() / loss_mask.sum()

        return encoder_loss

type_dict = {
    "semantic": SemanticLoss,
}

class EncoderLoss(nn.Module):
    def __init__(self, config, device='cuda'):
        super(EncoderLoss, self).__init__()
        self.device = device
        self.losses = []
        for item in config:
            if item['type'] in type_dict:
                # self.losses[item['type']] = type_dict[item['type']](weight=item['weight'], device=device)
                if 'args' not in item:
                    item['args'] = {}
                item['args']['device'] = device
                self.losses.append((item['type'], type_dict[item['type']](**item['args']), item['weight']))
            else:
                raise ValueError(f"Invalid loss type: {item['type']}")
    
    def forward(self, clean_audios, audio_embeds):
        loss_dict = {}
        assert len(self.losses) <= len(audio_embeds)
        for i in range(len(self.losses)):
            key, loss, weight = self.losses[i]
            loss_dict[key] = (loss(clean_audios, audio_embeds[i]), weight)
        return loss_dict