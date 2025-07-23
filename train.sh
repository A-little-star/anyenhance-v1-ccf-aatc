#!/bin/bash

accelerate launch --mixed_precision=fp16 --main_process_port=20096 trainer.py \
    --config "./config/anyenhance_v1.json" \
    --exp_path "./exp/"