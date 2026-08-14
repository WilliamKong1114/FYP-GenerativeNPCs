**Abstract**

This project presents a framework which integrates Large Language Models (LLMs) with Unity game engine to allow Non-Player Characters (NPCs) able to achieve complex social interactions and dynamic decision-making through highly coordinated communication between different modules, including Planning, Routing, Preference, Conversation, Communication, Observation and Reflection modules. 

Threading lock and concurrent LLM request is implemented to ensure system efficiency while maintaining data safety. A real-time data transmission and synchronization between the backend system and Unity is also achieved via persistence TCP (Transmission Control Protocol).

The agent architecture features a dual-layer memory system: ChromaDB is used for vector-based semantic retrieval to handle long-term memory,
while SQLite manages structured logs for short-term context. Inspired by generative agent research, the memory retrieval mechanism employs a hybrid heuristic that prioritizes information based on relevance, recency, and importance values, ensuring agents maintain consistent and context-aware dialogues. 

This project demonstrates the potential of generative agents from static assets to active and believable participants in digital worlds.

**The World Map with areas and objects**
<img width="1030" height="871" alt="image" src="https://github.com/user-attachments/assets/e472bafe-d546-4e20-affe-8f8d95e42cfb" />

**During a conversation**
<img width="1433" height="808" alt="image" src="https://github.com/user-attachments/assets/f7c00ade-c166-4e12-ba97-c462c6f9fc61" />

**Demo Video**
[![Project demo](https://img.youtube.com/vi/mK7Q7h48nN0/maxresdefault.jpg)](https://youtu.be/mK7Q7h48nN0)

**Detail System Report**
[Report.pdf](https://github.com/user-attachments/files/31078375/Final_Report.pdf)

