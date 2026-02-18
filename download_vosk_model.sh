#!/bin/bash
# Download and setup Vosk Russian language model

set -e

echo "📥 Downloading Vosk Russian model (small version)..."

MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_NAME="vosk-model-small-ru-0.22"
TARGET_DIR="./vosk-model-ru"

# Check if model already exists
if [ -d "$TARGET_DIR" ]; then
    echo "✅ Model already exists at $TARGET_DIR"
    echo "Remove it first to re-download: rm -rf $TARGET_DIR"
    exit 0
fi

# Download model
echo "Downloading from $MODEL_URL..."
wget -q --show-progress "$MODEL_URL" -o /dev/null -O "${MODEL_NAME}.zip"

# Extract
echo "Extracting..."
unzip -q "${MODEL_NAME}.zip"

# Rename
mv "${MODEL_NAME}" "$TARGET_DIR"

# Cleanup
rm "${MODEL_NAME}.zip"

echo "✅ Model downloaded successfully to $TARGET_DIR"
echo ""
echo "Model size:"
du -sh "$TARGET_DIR"
echo ""
echo "You can now start the bot: python bot.py"
