# 🦙 Ollama + Mistral Setup Guide

## Overview

This guide will help you set up Ollama with the Mistral model to power intelligent NPCs in your multiplayer game.

## 🚀 Quick Start

### 1. Install Ollama

**Linux/macOS:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download from [https://ollama.ai/download](https://ollama.ai/download)

### 2. Start Ollama Service

```bash
ollama serve
```

### 3. Pull Mistral Model

```bash
ollama pull mistral
```

### 4. Test Installation

```bash
ollama run mistral "Hello, how are you?"
```

## 🔧 Configuration

### Default Settings

The system uses these default Ollama settings:
- **URL**: `http://localhost:11434`
- **Model**: `mistral`
- **Temperature**: `0.7` (balanced creativity)
- **Max Tokens**: `500`
- **Timeout**: `30` seconds

### Custom Configuration

You can customize the Ollama settings by modifying `ollama_integration.py`:

```python
config = OllamaConfig(
    base_url="http://localhost:11434",
    model="mistral",
    temperature=0.8,        # More creative
    max_tokens=1000,        # Longer responses
    timeout=60              # Longer timeout
)
```

## 🧪 Testing

### 1. Test Ollama Connection

```bash
python test_ollama_npcs.py
```

### 2. Test in Game

1. Start the server: `uvicorn main:app --host 0.0.0.0 --port 8000`
2. Connect with CLI: `python websocket_cli.py --player 1`
3. Chat with NPCs: `/npc 1 Hello, what's your name?`

## 🎭 NPC Personalities

### Merchant NPCs
- **Traits**: Greedy, friendly, knowledgeable
- **Expertise**: Trade, economics, local gossip
- **Behavior**: Helpful but profit-focused

### Quest Giver NPCs
- **Traits**: Wise, helpful, experienced
- **Expertise**: Quests, lore, adventure
- **Behavior**: Mentor-like, mission-focused

### Combat Mob NPCs
- **Traits**: Aggressive, territorial, fearless
- **Expertise**: Combat, territory, threats
- **Behavior**: Hostile, challenging

## 🔍 Troubleshooting

### Common Issues

1. **"Cannot connect to Ollama"**
   - Ensure Ollama is running: `ollama serve`
   - Check if port 11434 is accessible
   - Verify firewall settings

2. **"Model not found"**
   - Pull the model: `ollama pull mistral`
   - Check available models: `ollama list`

3. **Slow responses**
   - Reduce `max_tokens` in configuration
   - Lower `temperature` for more focused responses
   - Check system resources

4. **Memory issues**
   - Restart Ollama service
   - Check available RAM
   - Consider using a smaller model variant

### Performance Tips

1. **Model Selection**
   - `mistral` - Good balance of speed and quality
   - `mistral:7b` - Faster, smaller model
   - `mistral:instruct` - Better for instruction following

2. **Response Optimization**
   - Keep system prompts concise
   - Limit context information to essentials
   - Use appropriate temperature settings

3. **Resource Management**
   - Monitor CPU and RAM usage
   - Restart Ollama periodically
   - Clear conversation cache if needed

## 🔮 Advanced Features

### Custom Models

You can use custom fine-tuned models:

```bash
# Create a custom model
ollama create mygame-npc -f Modelfile

# Use custom model
config = OllamaConfig(model="mygame-npc")
```

### Model Variants

Different Mistral variants available:
- `mistral:7b` - Fastest, good for real-time
- `mistral:13b` - Better quality, slower
- `mistral:instruct` - Optimized for instructions

### Prompt Engineering

Customize NPC behavior by modifying prompts in `ollama_integration.py`:

```python
def build_system_prompt(self, npc_name, npc_role, traits, domains):
    # Add custom instructions here
    custom_rules = """
    - Always respond in character
    - Use appropriate fantasy language
    - Provide helpful game hints
    """
    # ... rest of the method
```

## 📊 Monitoring

### Check Ollama Status

```bash
# List running models
ollama list

# Check service status
curl http://localhost:11434/api/tags

# Monitor resource usage
htop  # or your preferred system monitor
```

### Log Analysis

The game server will log Ollama interactions:
- ✅ Successful connections
- ⚠️ Fallback to rule-based responses
- ❌ Connection errors

## 🎯 Next Steps

1. **Test the integration** with `test_ollama_npcs.py`
2. **Start the game server** and try NPC chat
3. **Customize NPC personalities** by modifying prompts
4. **Experiment with different models** for various NPC types
5. **Add conversation memory** for persistent NPC relationships

## 🆘 Support

If you encounter issues:

1. Check Ollama logs: `ollama logs`
2. Verify model installation: `ollama list`
3. Test basic functionality: `ollama run mistral "test"`
4. Check system resources and network connectivity

The Ollama integration will automatically fall back to rule-based responses if there are any issues, ensuring your game continues to work even if Ollama is unavailable! 🎮✨
