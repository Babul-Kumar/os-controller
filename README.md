Botbro — Local AI Desktop Orchestration System
Botbro is a fully local, privacy-first AI desktop orchestration system for Windows built with Python.
It combines:


Local LLM reasoning


Desktop automation


Computer vision


Voice interaction


Autonomous rendering


Multi-step workflow execution


into a unified assistant capable of interacting with the user's desktop completely offline.
Unlike traditional cloud-based assistants, Botbro performs inference, automation, rendering, and orchestration directly on-device using local models powered by Ollama.

Overview
Botbro acts as an intelligent automation layer over the Windows desktop.
It can:


Understand natural language


Parse structured intents


Launch and control applications


Generate and write content


Draw images autonomously in MS Paint


Read screen content


Create/edit files


Execute multi-step workflows


Operate through both voice and GUI interfaces


The system is designed around a modular orchestration architecture with strong emphasis on:


Privacy


Offline execution


Deterministic automation


Extensibility


Real-time desktop interaction



Core Capabilities
🧠 Local AI Intent Engine
Botbro uses a local Ollama model (phi3) to convert natural language into structured JSON intents.
Features


Fully offline inference


Structured JSON prompting


Intent extraction


Tool selection


Command orchestration


Fallback heuristic parser


Local execution without cloud APIs


Example
User Input:
open vs code and create a python file for a calculator
Generated Intent:
{  "action": "create_file",  "app": "vscode",  "language": "python",  "topic": "calculator"}

🔒 Privacy & Security Layer
Botbro is designed with a privacy-first architecture.
PII Encryption Engine
Sensitive information is detected locally and masked before being sent to the LLM.
The system:


Detects sensitive entities


Encrypts them using AES-256-GCM


Replaces them with placeholders


Restores them after inference


Security Characteristics


No cloud inference


No telemetry


No external data storage


Fully local execution


Offline model usage


Temporary encrypted prompt masking



🖥 Desktop Orchestration Layer
Botbro can dynamically interact with the Windows desktop using:


Windows APIs


OpenCV


PyAutoGUI


pywin32


psutil


winreg


Supported Automation


Open applications


Focus windows


Close applications


Type text


Paste generated content


Create files


Navigate folders


Interact with UI elements


Launch IDEs


Read screen content


Supported Applications


Chrome


VS Code


Notepad


Microsoft Word


Microsoft Excel


Paint


File Explorer


Custom executables



🎨 Autonomous Rendering & Drawing Engine
One of Botbro’s most advanced subsystems is the autonomous rendering engine capable of drawing images directly in Microsoft Paint.
The rendering system evolved from simple mouse automation into a full contour-processing and rendering orchestration pipeline.
Rendering Pipeline
Natural Language Prompt        ↓Image Generation / Retrieval        ↓Preprocessing Pipeline        ↓Contour Extraction        ↓Vector Optimization        ↓Path Planning        ↓Rendering Backend        ↓MS Paint Drawing

Rendering Engine Features
Image Processing


Adaptive preprocessing


Histogram-based threshold polarity detection


Dynamic thresholding


Noise reduction


Edge enhancement


Morphological operations


Contour hierarchy analysis


Vector & Geometry Processing


Potrace vectorization


OpenCV contour extraction


Douglas-Peucker simplification


Curvature-aware adaptive sampling


Contour stitching


Nearest-neighbor path optimization


Scale-aware smoothing


Rendering Optimization


KD-tree contour ordering


Reduced pen lifts


Adaptive point density


Dynamic approximation strategies


Travel-distance optimization


Backend-aware rendering policies


Supported Drawing Types


Logos


Icons


Sketches


Anime line art


Shapes


Symbols


Abstract art


Geometric figures



🎙 Voice Interaction System
Botbro supports fully voice-controlled interaction.
Speech Input


SpeechRecognition


PyAudio microphone capture


Continuous listening support


Speech Output


pyttsx3 offline TTS


Spoken confirmations


Task completion feedback



🧩 Modular Architecture
Botbro is organized as a modular orchestration framework.
botbro/│├── automation/├── core/├── services/├── gui/├── voice/├── plugins/├── utils/├── assets/├── config/└── tests/

Architecture Overview
User Input (Voice / GUI)            ↓     Intent Processing            ↓      PII Sanitization            ↓      Local LLM Parsing            ↓     Structured JSON Intent            ↓      Command Executor            ↓  Automation / Rendering Layer            ↓     Desktop Interaction

Directory Structure
/core
Central orchestration engine.
Contains


CommandExecutor


MemoryManager


PIIEngine


Session handling


Runtime coordination



/services
AI communication layer.
Contains


AIService


OllamaService


Prompt templates


JSON intent parsing


Response validation



/automation
Execution and rendering modules.
Contains


AppController


DrawEngine


ImageTracer


MouseAutomator


ScreenReader


WebAutomator


FileFinder



/gui
PyQt5 graphical interface.
Features


Async chat interface


Live command interaction


Non-blocking task execution



/voice
Voice input/output subsystem.
Features


Microphone input


Speech recognition


Offline text-to-speech



Technical Highlights
Rendering & Geometry


Contour hierarchy extraction


KD-tree path optimization


Curvature-aware adaptive sampling


Dynamic preprocessing pipelines


Rendering policy orchestration


Vector-assisted plotting


Contour graph processing


AI & Orchestration


Structured JSON prompting


Offline LLM orchestration


Intent fallback heuristics


Modular command execution


Context-aware automation


System Engineering


Asynchronous GUI execution


SQLite-based memory


Modular subsystem architecture


Windows API integration


Fully local execution pipeline



Installation
1. Clone Repository
git clone https://github.com/yourusername/botbro.gitcd botbro

2. Create Virtual Environment
python -m venv venv
Activate:
Windows
venv\Scripts\activate

3. Install Dependencies
pip install -r requirements.txt

Major Dependencies
CategoryLibrariesGUIPyQt5VisionOpenCV, PotraceVoiceSpeechRecognition, PyAudio, pyttsx3Automationpyautogui, pywin32, pygetwindowAIOllamaSystempsutil, winregUtilitypyperclip, numpy, scipy

4. Install Ollama
Download Ollama from the official website.
Then pull the required model:
ollama pull phi3

5. Run Botbro
python main.py

Example Commands
Desktop Automation
open chrome
open notepad and write a poem
open vscode and create a python calculator

File Operations
find resume.pdf on my computer
create a javascript file for todo app

Rendering Commands
open paint and draw a dragon
draw anime girl
draw geometric wolf logo

Screen Understanding
what is on my screen

Performance Characteristics
CapabilityCharacteristicsAI InferenceFully localRenderingAdaptive vector plottingVoice ProcessingOfflineDrawing ComplexityHandles dense contour graphsStorageSQLite session memoryNetworkingOptional only for image retrieval

Platform Requirements
Supported OS


Windows 10


Windows 11


Required Applications


Microsoft Paint


Google Chrome (optional)


VS Code (optional)



Packaging
You can package Botbro into a standalone executable using PyInstaller.
pip install pyinstaller
Build:
pyinstaller --onefile --windowed --name Botbro main.py

Design Philosophy
Botbro is built around several core principles:
Local First
All critical inference and orchestration happen locally.
Privacy by Default
Sensitive information never leaves the device unprotected.
Modular Architecture
Subsystems are loosely coupled and independently extensible.
Deterministic Automation
Actions are explicitly orchestrated through structured intents.
Extensible Rendering
The rendering engine is designed to evolve toward true vector plotting and advanced motion planning.

Future Roadmap
Planned Features


Screenshot feedback validation


Bézier curve rendering


SVG-native rendering pipeline


Browser automation agents


RAG memory integration


Multi-agent orchestration


GPU-assisted rendering


Real-time screen segmentation


Advanced vector path planning


Adaptive motion interpolation



Current Limitations


Windows-only architecture


Dependent on Microsoft Paint for rendering


Some automation tasks depend on screen focus


Complex drawings may require extended rendering time


Voice recognition quality depends on microphone quality



Research & Engineering Areas
Botbro now touches multiple advanced engineering domains:


Desktop automation


Computer vision


Computational geometry


Rendering systems


Path optimization


Vector graphics


AI orchestration


Human-computer interaction



License
MIT License

Final Note
Botbro started as a desktop automation assistant and evolved into a full local AI orchestration and rendering system capable of:


multimodal interaction


intelligent automation


contour-based rendering


structured AI execution


offline desktop control


The project now combines:


AI systems engineering


rendering orchestration


automation infrastructure


vector processing


real-time desktop interaction


into a unified local-first assistant architecture.
