#! /bin/bash

python infer.py \
    --config_path "./config/anyenhance_v1.json" \
    --ckpt_path "./pretrained/epoch-83-step-200000-loss-4.4187/model.pt" \
    --input_file "./dataset/debug_audio/noisy/2.wav" \
    --output_folder "./output/"