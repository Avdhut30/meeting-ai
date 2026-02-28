from gtts import gTTS

text = """
Meeting Title: AI Product Sprint Planning & Technical Review
Date: 20 February 2026
Duration: Approximately 45 minutes
Participants: Avdhut (Product Lead), Rohit (Frontend Engineer), Neha (Backend Engineer), Karan (DevOps), Priya (QA)

Avdhut: Good morning everyone. Let’s begin the sprint planning session for our AI Meeting Intelligence Platform. The main objective today is to review the current development progress, identify blockers, finalize the MVP scope, and assign deadlines for the next sprint.

Rohit: Good morning. From the frontend side, the authentication UI is completed. Users can register and log in successfully. However, dashboard integration with backend APIs is still pending.

Neha: On the backend side, user authentication endpoints are working. JWT token validation is functional. Database migrations are successfully implemented using Alembic. The meeting creation endpoint is completed.

Avdhut: That’s good progress. What about transcript upload functionality?

Neha: Transcript upload endpoint is implemented. However, we still need validation for file size and format. Currently, only .txt files are accepted.

Priya: From QA testing perspective, I found that when uploading a very large transcript, the system response time increases significantly.

Avdhut: That’s expected. We haven’t implemented chunking and background processing yet. Neha, what’s the status of chunking logic?

Neha: I have implemented a basic chunking algorithm. It splits text into 500-token chunks with 100-token overlap. However, we need better handling for extremely long paragraphs.

Avdhut: Good. Let’s finalize chunk size to 700 tokens with 150 overlap for better semantic retention.

Karan: Once chunking is stable, we need to integrate embedding generation. Are we using OpenAI embeddings or sentence-transformers locally?

Avdhut: For MVP, we will use OpenAI embeddings. Later we can experiment with local models to reduce cost.

Rohit: On frontend, I will build a separate tab to display transcript chunks and embeddings metadata for debugging purposes.

Avdhut: Excellent idea. Transparency helps debugging.

Priya: We also need structured summary output. What format are we expecting?

Neha: I propose structured JSON output:
- summary
- key_topics
- decisions
- action_items with owner and due_date
- blockers

Avdhut: Agreed. That structure works.

Karan: Deployment pipeline is still incomplete. We need Dockerization for backend and frontend separately.

Avdhut: Karan, please prioritize Docker setup by Wednesday.

Karan: Noted. I will complete Dockerfile creation and docker-compose configuration by Wednesday evening.

Rohit: I have a blocker regarding CORS configuration between frontend and backend. The browser blocks API calls in development mode.

Neha: That’s a middleware issue. I will fix CORS configuration today.

Avdhut: Good. Let's list current action items.

Action Item 1:
Owner: Rohit
Task: Complete dashboard integration with backend APIs
Deadline: Thursday

Action Item 2:
Owner: Neha
Task: Optimize chunking algorithm and add file validation
Deadline: Tomorrow evening

Action Item 3:
Owner: Karan
Task: Implement Docker setup and deployment pipeline
Deadline: Wednesday evening

Action Item 4:
Owner: Priya
Task: Perform stress testing with 50-page transcripts
Deadline: Friday

Action Item 5:
Owner: Avdhut
Task: Test embedding retrieval quality and RAG answer accuracy
Deadline: Wednesday afternoon

Priya: Regarding testing, we also need edge case handling for empty transcripts and corrupted files.

Neha: I will add input validation and error handling for invalid uploads.

Avdhut: Another topic: How are we handling hallucination in RAG responses?

Neha: We will restrict the LLM prompt to only answer based on retrieved chunks. If information is not present, it must respond with “Not found in transcript.”

Avdhut: Perfect. That reduces misinformation.

Rohit: Should we implement feedback system for answers?

Avdhut: Yes. Add thumbs up and thumbs down functionality for answers. Store feedback in database.

Karan: That will help evaluate retrieval quality later.

Priya: We should also log response latency for performance monitoring.

Avdhut: Agreed. Add basic logging for:
- transcription time
- chunking time
- embedding generation time
- answer generation time

Neha: One concern is cost optimization. Embedding long transcripts can be expensive.

Avdhut: For now, MVP focus is functionality. Cost optimization will be Phase 2.

Rohit: When is the demo scheduled?

Avdhut: Demo is on Sunday at 5 PM. MVP must be stable by Saturday night.

Priya: What defines MVP completion?

Avdhut: MVP checklist:
- User authentication
- Transcript upload
- Chunking and embeddings
- Summary generation
- Action item extraction
- Ask Meeting (RAG with citations)
- Basic dashboard UI

Karan: Understood.

Neha: One more technical point. We should create a meeting status flow:
created → uploaded → processing → processed → failed

Avdhut: That’s correct. Add that to database schema.

Rohit: I will update UI to show meeting status badges.

Priya: We also need export functionality for meeting minutes in PDF format.

Avdhut: PDF export can be optional if time permits.

Karan: I suggest we finalize architecture documentation before demo.

Avdhut: Yes, I will prepare architecture diagram and system flow documentation by Friday.

Priya: That covers everything from QA side.

Avdhut: Final decision:
The MVP must be completed and tested by Saturday night for Sunday demo.

If no further questions, let’s conclude the meeting.

Everyone: Agreed.

Meeting adjourned.
"""

tts = gTTS(text)
tts.save("big_meeting_test.mp3")

print("Audio file generated successfully!")