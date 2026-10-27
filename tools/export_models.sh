#!/usr/bin/env bash
# Export the YOLO models to ONNX in a throwaway environment so torch and
# Ultralytics never become project dependencies. Writes models/*.onnx:
#   yolo26n, yolov8n                 person detectors, fixed 640 input
#   yolo26n-pose, yolov8n-pose       full-frame pose, fixed 640 input
#   *-pose-dynamic                   pose on batched person crops (dynamic shapes)
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p "${EXPORT_ENV:-.export-env}"
ENV_DIR="$(cd "${EXPORT_ENV:-.export-env}" && pwd)"  # portable: macOS realpath has no -m
uv venv -q --allow-existing "$ENV_DIR" --python 3.12
uv pip install -q --python "$ENV_DIR/bin/python" torch==2.14.1 torchvision==0.29.1 \
    --index-url https://download.pytorch.org/whl/cpu
uv pip install -q --python "$ENV_DIR/bin/python" ultralytics==8.4.172 onnx==1.23.1 onnxslim==0.1.97

mkdir -p models
cd models
yolo="$ENV_DIR/bin/yolo"
for model in yolo26n yolov8n; do
    "$yolo" export model="$model.pt" format=onnx imgsz=640
done
for model in yolo26n-pose yolov8n-pose; do
    "$yolo" export model="$model.pt" format=onnx dynamic=True
    mv "$model.onnx" "$model-dynamic.onnx"
    "$yolo" export model="$model.pt" format=onnx imgsz=640
done
