#! /bin/bash

python infer.py \
    --config_path ./config/anyenhance_v1.json \
    --ckpt_path pretrained/epoch-83-step-200000-loss-4.4187/model.pt \
    --input_folder /home/work_nfs16/fe_data/data/CCF_AATC_2025_Challenge/Track1/dev_dataset/development_set/noisy \
    --output_folder ./decode/anyenhance_v1_epoch69/
    # --input_file ./dataset/debug_audio/noisy/2.wav \