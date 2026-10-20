"""The synthetic bank and night `sleep_calls` measures: a developer's bank of ~270 pages whose names share the generic
words real names share ("model", "google", "design", "project", a first name), and eight conversations that mention
existing pages by name, by a short form and by a first name, new things that share a word with many pages, and a few
changes of state. Placeholders only (`Owner Example`, `Carol Example`, `Alpha Project`); the tools and companies are
public products, nothing from anyone's bank.

``PAGES`` rows are ``type|name|summary|fact; fact``; ``CONVERSATIONS`` are ``(day, origin, title, turns)``.
"""
from __future__ import annotations

OWNER = "Owner Example"

PAGES = """
person|Carol Example|Carol Example is a backend engineer who works with Owner Example on Alpha Project.|Carol Example reviews Alpha Project's pull requests.; Carol Example lives in Lisbon.
person|Carol Sample|Carol Sample is a classmate of Owner Example from the machine learning course.|Carol Sample studies statistics.
person|Dana Example|Dana Example is Owner Example's thesis advisor at Example University.|Dana Example works on reinforcement learning.; Dana Example meets Owner Example every two weeks.
person|Erin Example|Erin Example is a recruiter at Hooli who contacted Owner Example about a role.|Erin Example scheduled a first call in September 2026.
person|Frank Example|Frank Example is an old friend of Owner Example who runs a small design studio.|Frank Example designed the Alpha Project logo.
person|Frank Sample|Frank Sample is the landlord of Owner Example's flat in Madrid.|Frank Sample handles the flat's repairs.
person|Grace Example|Grace Example is a product manager Owner Example met at a hackathon.|Grace Example works at Globex.
person|Henry Example|Henry Example is Owner Example's flatmate.|Henry Example cooks on Sundays.
person|Iris Example|Iris Example is a researcher who co-authored a workshop paper with Owner Example.|Iris Example works on knowledge graphs.
person|Jack Example|Jack Example is Owner Example's brother.|Jack Example lives in Barcelona.
person|Karen Example|Karen Example teaches the German course Owner Example considered.|
person|Leo Example|Leo Example is a friend from university who works at Initech.|Leo Example plays chess with Owner Example online.
person|Maria Example|Maria Example is Owner Example's mother.|Maria Example lives in Madrid.
person|Nina Example|Nina Example is a designer who reviewed the Personal Website mockups.|
person|Oscar Example|Oscar Example is a teaching assistant for the data science course.|
person|Paula Example|Paula Example is a founder Owner Example advised about agent memory.|Paula Example runs a two-person startup.
person|Quinn Example|Quinn Example is a gym partner of Owner Example.|
person|Rita Example|Rita Example is a colleague from Owner Example's internship at Initech.|
person|Sam Example|Sam Example is the organizer of the local Python meetup.|
person|Tess Example|Tess Example is a cousin of Owner Example who studies medicine.|
person|Uma Example|Uma Example is a PhD student in Dana Example's lab.|Uma Example works on reward modelling.
person|Victor Example|Victor Example is a contractor who helped set up the Home Server network.|
person|Wendy Example|Wendy Example is an editor at a tech newsletter Owner Example reads.|
project|Alpha Project|Alpha Project is Owner Example's personal memory app that turns conversations into a knowledge graph.|Alpha Project stores its data in PostgreSQL.; Alpha Project's backend is written with FastAPI.; Alpha Project uses FAISS for vector search.
project|Beta Project|Beta Project is a browser extension Owner Example built to save tabs into notes.|Beta Project was paused in August 2026.
project|Gamma Project|Gamma Project is a small CLI that summarizes git logs.|
project|Thesis Project|Thesis Project is Owner Example's master's thesis on evaluating reinforcement learning agents.|The thesis is supervised by Dana Example.; The thesis evaluation uses the Atari benchmark.
project|Thesis Evaluation|Thesis Evaluation is the experiment suite of Owner Example's thesis.|It runs on the university GPU cluster.
project|Research Paper Draft|Research Paper Draft is a workshop paper on agent memory written with Iris Example.|The deadline is in November 2026.
project|Personal Website|Personal Website is Owner Example's homepage built with Next.js.|It is hosted on Vercel.
project|Portfolio Website|Portfolio Website is an older static portfolio Owner Example no longer updates.|
project|Home Server|Home Server is Owner Example's self-hosted server running media and backups.|Home Server runs on a Raspberry Pi.; Home Server is reachable through Tailscale.
project|Home Automation|Home Automation is a plan to automate the flat's lights and heating.|
project|Mobile App|Mobile App is a SwiftUI companion app for Alpha Project.|
project|Budget Tracker App|Budget Tracker App is a spreadsheet-based budget tracker Owner Example built.|
project|Habit Tracker|Habit Tracker is a small app Owner Example started for tracking habits.|
project|Recipe App|Recipe App is a side project that stores family recipes.|
project|Chess Engine|Chess Engine is a toy chess engine Owner Example wrote in Rust.|
project|Discord Bot|Discord Bot is a bot Owner Example wrote for a study group server.|
project|Telegram Bot|Telegram Bot forwards saved links from Telegram into notes.|
project|Keyboard Build|Keyboard Build is a custom mechanical keyboard Owner Example assembled.|
project|Game Jam Entry|Game Jam Entry is a pixel art game made in 48 hours.|
project|Pixel Art Game|Pixel Art Game is a slow-moving game project made with Godot.|
project|Hackathon Project|Hackathon Project is the agent prototype Owner Example built at a hackathon in May 2026.|
project|Startup Idea|Startup Idea is a note collecting Owner Example's startup ideas.|
project|Newsletter|Newsletter is a monthly email Owner Example writes about tools.|
project|Machine Learning Course|Machine Learning Course is the university course Owner Example took in spring 2026.|
project|Data Science Course|Data Science Course is an online course Owner Example finished in 2025.|
project|Capstone Project|Capstone Project was Owner Example's undergraduate capstone on recommender systems.|
project|Internship Project|Internship Project was the data pipeline Owner Example built at Initech.|
project|Open Source Contribution|Open Source Contribution tracks Owner Example's pull requests to open source projects.|
project|Flat Search|Flat Search is Owner Example's search for a new flat in Madrid.|
project|Berlin Trip|Berlin Trip is a planned visit to Berlin in December 2026.|
project|Marathon Training|Marathon Training is Owner Example's plan to run a marathon in spring 2027.|
project|Waitlist Site|Waitlist Site is a landing page that collects sign-ups for Alpha Project.|
project|Alpha Project Demo|Alpha Project Demo is the recorded demo video of Alpha Project.|
tool|Python|Python is the main programming language Owner Example uses.|
tool|Python Script|Python Script is a folder of small automation scripts Owner Example keeps.|
tool|FastAPI|FastAPI is the Python web framework Owner Example uses for backends.|
tool|SwiftUI|SwiftUI is Apple's UI framework Owner Example uses for the Mobile App.|
tool|SQLite|SQLite is the embedded database Owner Example likes for local apps.|
tool|PostgreSQL|PostgreSQL is a relational database Owner Example used in several projects.|
tool|Redis|Redis is an in-memory store Owner Example used for queues.|
tool|Docker|Docker is the container tool Owner Example uses for deployments.|
tool|Docker Compose|Docker Compose runs the Home Server's services.|
tool|Kubernetes|Kubernetes is a container orchestrator Owner Example learned at the internship.|
tool|GitHub|GitHub hosts Owner Example's repositories.|
tool|GitHub Actions|GitHub Actions runs Alpha Project's tests.|
tool|GitHub Copilot|GitHub Copilot is a code assistant Owner Example tried in 2025.|
tool|VS Code|VS Code is the editor Owner Example used before switching.|
tool|Xcode|Xcode is Apple's IDE Owner Example uses for SwiftUI work.|
tool|Claude Code|Claude Code is the coding agent Owner Example uses daily.|
tool|Claude Desktop|Claude Desktop is the desktop chat app Owner Example uses for writing.|
tool|Claude API|Claude API is the model API Alpha Project calls for consolidation.|
tool|OpenAI API|OpenAI API is the model API Owner Example used for embeddings in 2025.|
tool|ChatGPT|ChatGPT is a chat assistant Owner Example uses for quick questions.|
tool|Codex CLI|Codex CLI is a coding agent Owner Example tried in September 2026.|
tool|Cursor|Cursor is an AI code editor Owner Example used for a few months.|
tool|Ollama|Ollama runs local models on Owner Example's laptop.|
tool|LiteLLM|LiteLLM is the model routing library Alpha Project uses.|
tool|PyTorch|PyTorch is the deep learning framework of the thesis experiments.|
tool|TensorFlow|TensorFlow is a framework Owner Example used in the data science course.|
tool|Hugging Face|Hugging Face hosts the models and datasets Owner Example downloads.|
tool|Hugging Face Transformers|Hugging Face Transformers is the library Owner Example uses to load language models.|
tool|Jupyter Notebook|Jupyter Notebook is where Owner Example explores data.|
tool|Google Colab|Google Colab gives Owner Example free GPUs for quick experiments.|
tool|Google Drive|Google Drive stores Owner Example's university documents.|
tool|Google Docs|Google Docs is where Owner Example drafts documents with others.|
tool|Google Calendar|Google Calendar holds Owner Example's university schedule.|
tool|Google Translate|Google Translate is what Owner Example uses for quick translations.|
tool|Google Maps|Google Maps is the navigation app Owner Example uses.|
tool|Notion|Notion is Owner Example's main notes app.|Owner Example keeps project plans in Notion.
tool|Obsidian|Obsidian is a markdown notes app Owner Example tried in 2025.|
tool|Slack|Slack is the chat tool of Owner Example's lab.|
tool|Discord|Discord hosts Owner Example's study group.|
tool|Zoom|Zoom is used for thesis meetings.|
tool|Figma|Figma is the design tool Owner Example uses for mockups.|
tool|Linear|Linear tracks Alpha Project's issues.|
tool|Vercel|Vercel hosts the Personal Website.|
tool|Supabase|Supabase is the hosted Postgres Owner Example uses for the Waitlist Site.|
tool|Next.js|Next.js is the React framework of the Personal Website.|
tool|React|React is the UI library Owner Example uses for web work.|
tool|React Native|React Native is a mobile framework Owner Example considered for Mobile App.|
tool|Node.js|Node.js runs Owner Example's JavaScript tooling.|
tool|TypeScript|TypeScript is the language of Owner Example's web projects.|
tool|Rust|Rust is the language of the Chess Engine.|
tool|Swift|Swift is the language of Mobile App.|
tool|Homebrew|Homebrew installs Owner Example's command-line tools.|
tool|Tailscale|Tailscale connects Owner Example's devices to the Home Server.|
tool|Cloudflare Tunnel|Cloudflare Tunnel exposed a demo of Alpha Project once.|
tool|AWS S3|AWS S3 stores backups of the Home Server.|
tool|Firebase|Firebase was the backend of the Recipe App.|
tool|MongoDB|MongoDB was the database of the Capstone Project.|
tool|Neo4j|Neo4j is a graph database Owner Example evaluated for Alpha Project.|
tool|sqlite-vec|sqlite-vec is a SQLite extension for vector search.|
tool|FAISS|FAISS is a vector search library Alpha Project used.|
tool|LangChain|LangChain is an agent framework Owner Example tried and dropped.|
tool|LlamaIndex|LlamaIndex is a retrieval framework Owner Example read about.|
tool|MCP Server|MCP Server is the Model Context Protocol server Alpha Project exposes to agents.|
tool|MCP Inspector|MCP Inspector is the debugging tool for MCP servers.|
tool|Whisper|Whisper is the speech recognition model Owner Example uses for voice notes.|
tool|Raycast|Raycast is Owner Example's launcher on macOS.|
tool|Arc Browser|Arc Browser was Owner Example's browser in 2025.|
tool|Chrome|Chrome is Owner Example's main browser.|
tool|Chrome Extension|Chrome Extension is the packaging of Beta Project.|
tool|Apple Notes|Apple Notes holds Owner Example's quick notes on the phone.|
tool|Apple Shortcuts|Apple Shortcuts automates small phone tasks for Owner Example.|
tool|iTerm2|iTerm2 is Owner Example's terminal.|
tool|tmux|tmux keeps Owner Example's terminal sessions alive.|
tool|Neovim|Neovim is the editor Owner Example uses now.|
tool|Git|Git versions all of Owner Example's code.|
tool|pytest|pytest runs Alpha Project's Python tests.|
tool|uv|uv manages Python environments for Owner Example.|
tool|NumPy|NumPy is the array library in every Owner Example experiment.|
tool|pandas|pandas is the dataframe library Owner Example uses.|
tool|Matplotlib|Matplotlib draws the thesis plots.|
tool|scikit-learn|scikit-learn is the classic machine learning library Owner Example uses for baselines.|
tool|OpenCV|OpenCV was used in a computer vision assignment.|
tool|Godot|Godot is the game engine of the Pixel Art Game.|
tool|Aseprite|Aseprite is the pixel art editor Owner Example uses.|
tool|Raspberry Pi|Raspberry Pi is the single-board computer that runs the Home Server.|
tool|Mac Mini|Mac Mini is a desktop computer Owner Example bought in 2026.|
tool|MacBook Pro|MacBook Pro is Owner Example's laptop.|
tool|iPad Pro|iPad Pro is the tablet Owner Example reads papers on.|
tool|Kindle|Kindle is the e-reader Owner Example uses for books.|
tool|Anki|Anki is the flashcard app Owner Example uses for vocabulary.|
tool|Zotero|Zotero manages the thesis references.|
tool|Overleaf|Overleaf is where the thesis is written.|
tool|LaTeX|LaTeX typesets the thesis and the paper.|
tool|DeepL|DeepL is the translator Owner Example prefers for German.|
tool|Spotify|Spotify is Owner Example's music app.|
tool|YouTube|YouTube is where Owner Example watches lectures.|
tool|Duolingo|Duolingo is the language app Owner Example uses for German.|
tool|Strava|Strava records Owner Example's runs.|
tool|Garmin Watch|Garmin Watch is Owner Example's running watch.|
tool|Wispr Flow|Wispr Flow is the dictation app Owner Example uses.|
tool|Atari Benchmark|Atari Benchmark is the suite of Atari games the thesis evaluates agents on.|
tool|Stable Baselines|Stable Baselines is a reinforcement learning library the thesis uses for baselines.|
tool|Gymnasium|Gymnasium is the environment API the thesis experiments use.|
tool|Weights Dashboard|Weights Dashboard is the lab's self-hosted experiment dashboard.|
concept|Machine Learning|Machine Learning is the field Owner Example studies.|
concept|Deep Learning|Deep Learning is the part of machine learning Owner Example's thesis relies on.|
concept|Reinforcement Learning|Reinforcement Learning is the topic of Owner Example's thesis.|
concept|Transfer Learning|Transfer Learning came up in the machine learning course.|
concept|Federated Learning|Federated Learning is a topic Owner Example read one paper about.|
concept|Active Learning|Active Learning is a labeling strategy Owner Example considered for the internship.|
concept|Spaced Repetition|Spaced Repetition is how Owner Example learns vocabulary with Anki.|
concept|Memory Consolidation|Memory Consolidation is the idea behind Alpha Project's nightly processing.|
concept|Episodic Memory|Episodic Memory is the raw layer of Alpha Project.|
concept|Working Memory|Working Memory came up in a cognitive science lecture.|
concept|Semantic Memory|Semantic Memory is the consolidated layer of Alpha Project.|
concept|Knowledge Graph|Knowledge Graph is the structure Alpha Project builds.|
concept|Graph Database|Graph Database is a category Owner Example compared for Alpha Project.|
concept|Vector Database|Vector Database is a category of stores for embeddings.|
concept|Vector Search|Vector Search is how Alpha Project finds related pages.|
concept|Semantic Search|Semantic Search is meaning-based retrieval in Alpha Project.|
concept|Full-Text Search|Full-Text Search is the word-based index beside vector search in Alpha Project.|
concept|Prompt Engineering|Prompt Engineering is a daily part of Owner Example's work on Alpha Project.|
concept|Prompt Caching|Prompt Caching cuts the cost of repeated prompts.|
concept|Context Window|Context Window limits how much a model reads at once.|
concept|Retrieval-Augmented Generation|Retrieval-Augmented Generation is the pattern of answering from retrieved text.|
concept|Fine-Tuning|Fine-Tuning is training a pretrained model further on new data.|
concept|LoRA Fine-Tuning|LoRA Fine-Tuning is a parameter-efficient method Owner Example tried in the course.|
concept|Model Evaluation|Model Evaluation is how Owner Example compares models in the thesis.|
concept|Model Distillation|Model Distillation is a technique Owner Example read about.|
concept|Language Model|Language Model is a model trained to predict text.|
concept|Business Model|Business Model is a topic in Owner Example's startup notes.|
concept|Pricing Model|Pricing Model is how Alpha Project might charge in the future.|
concept|Temporal Decay|Temporal Decay is how Alpha Project lets unmentioned pages fade.|
concept|Entity Resolution|Entity Resolution is how Alpha Project decides whether two names are the same thing.|
concept|Entity Extraction|Entity Extraction is the first stage of Alpha Project's pipeline.|
concept|Data Pipeline|Data Pipeline is a recurring pattern in Owner Example's projects.|
concept|Data Cleaning|Data Cleaning took most of the internship.|
concept|Data Privacy|Data Privacy is a design principle of Alpha Project.|
concept|Privacy Policy|Privacy Policy is a document the Waitlist Site needs.|
concept|Open Source|Open Source is how Owner Example plans to release Alpha Project.|
concept|Open Source License|Open Source License is the license choice for Alpha Project.|
concept|Remote Work|Remote Work is how Owner Example worked during the internship.|
concept|Deep Work|Deep Work is Owner Example's practice of long focused blocks.|
concept|Time Blocking|Time Blocking is how Owner Example plans the week.|
concept|Morning Routine|Morning Routine is Owner Example's routine of running before work.|
concept|Sleep Schedule|Sleep Schedule is something Owner Example tries to keep regular.|
concept|Code Review|Code Review is a practice Owner Example does with Carol Example.|
concept|Pair Programming|Pair Programming is how Owner Example works with Carol Example on hard bugs.|
concept|Test-Driven Development|Test-Driven Development is a practice Owner Example follows on Alpha Project.|
concept|Unit Testing|Unit Testing covers Alpha Project's services.|
concept|Integration Testing|Integration Testing covers Alpha Project's pipeline end to end.|
concept|Continuous Integration|Continuous Integration runs on every Alpha Project pull request.|
concept|Design System|Design System is the set of rules for Alpha Project's interface.|
concept|Design Tokens|Design Tokens are the named colors and sizes of the design system.|
concept|Dark Mode|Dark Mode is supported in Alpha Project's app.|
concept|Accessibility|Accessibility is a requirement for the Mobile App.|
concept|User Onboarding|User Onboarding is the first-run flow of Alpha Project.|
concept|Product Market Fit|Product Market Fit is a startup concept Owner Example reads about.|
concept|Startup Fundraising|Startup Fundraising is a topic Owner Example discussed with Paula Example.|
concept|Agent Memory|Agent Memory is the research area of Alpha Project and the workshop paper.|
concept|Agent Harness|Agent Harness is the program that runs a coding agent.|
concept|Multi-Agent Systems|Multi-Agent Systems is a topic Owner Example explored at the hackathon.|
concept|Tool Use|Tool Use is how agents call functions.|
concept|Computer Use|Computer Use is agents operating a computer's interface.|
concept|Speech Recognition|Speech Recognition turns Owner Example's voice notes into text.|
concept|Image Generation|Image Generation is a topic Owner Example plays with on weekends.|
concept|Pixel Art|Pixel Art is a hobby of Owner Example.|
concept|Game Design|Game Design is a hobby interest of Owner Example.|
concept|Language Learning|Language Learning is Owner Example's ongoing effort to learn German.|
concept|Public Speaking|Public Speaking is a skill Owner Example wants to improve.|
concept|Thesis Writing|Thesis Writing is the current phase of the thesis.|
concept|Literature Review|Literature Review is the related-work chapter of the thesis.|
concept|Research Methods|Research Methods was a first-year course.|
concept|Statistics|Statistics is the basis of the thesis's significance tests.|
concept|Linear Algebra|Linear Algebra is a subject Owner Example reviews before interviews.|
concept|Graph Theory|Graph Theory is a subject Owner Example enjoys.|
concept|Information Theory|Information Theory is a subject Owner Example read a book about.|
concept|Burnout|Burnout is something Owner Example worried about in spring 2026.|
concept|Productivity System|Productivity System is Owner Example's mix of notes, calendar and weekly planning.|
concept|Note-Taking|Note-Taking is a habit Owner Example cares about.|
concept|Second Brain|Second Brain is the idea of an external memory system.|
concept|Personal Knowledge Management|Personal Knowledge Management is the field Alpha Project belongs to.|
concept|Zettelkasten|Zettelkasten is a note method Owner Example read about.|
concept|Journaling|Journaling is a nightly habit of Owner Example.|
concept|Meditation|Meditation is something Owner Example does a few times a week.|
concept|Running|Running is Owner Example's main sport.|
concept|Strength Training|Strength Training is what Owner Example does with Quinn Example.|
concept|Nutrition|Nutrition is something Owner Example tracks while training.|
concept|Coffee Brewing|Coffee Brewing is a hobby of Owner Example.|
concept|Cooking|Cooking is something Owner Example does with Henry Example.|
concept|Budgeting|Budgeting is how Owner Example keeps track of money.|
concept|Index Funds|Index Funds are where Owner Example puts savings.|
concept|Job Search|Job Search is Owner Example's search for a role after the thesis.|
concept|Interview Preparation|Interview Preparation is Owner Example's practice for technical interviews.|
concept|Resume Writing|Resume Writing is a task on Owner Example's job search list.|
concept|Operating System|Operating System design was a course Owner Example liked.|
concept|Recommender Systems|Recommender Systems was the topic of the Capstone Project.|
concept|Computer Vision|Computer Vision is a field Owner Example studied briefly.|
concept|Reward Shaping|Reward Shaping is a technique discussed in the thesis.|
concept|Policy Gradient|Policy Gradient methods are a family the thesis compares.|
concept|Weekly Planning|Weekly Planning is Owner Example's Sunday planning session.|
concept|Self-Hosting|Self-Hosting is Owner Example's preference for running services at home.|
company|Initech|Initech is the company where Owner Example did an internship.|
company|Globex|Globex is a company where Grace Example works.|
company|Hooli|Hooli is a large tech company recruiting Owner Example.|
company|Acme Corp|Acme Corp is a client of Frank Example's studio.|
company|Umbrella Labs|Umbrella Labs is a startup Owner Example interviewed with in 2025.|
company|Example University|Example University is where Owner Example studies.|
company|Anthropic|Anthropic makes the Claude models.|
company|OpenAI|OpenAI makes the GPT models.|
company|Google|Google makes Colab and Drive.|
company|Apple|Apple makes Owner Example's laptop.|
company|Microsoft|Microsoft owns GitHub.|
company|Hugging Face Inc|Hugging Face Inc is the company behind the Hugging Face hub.|
location|Madrid|Madrid is where Owner Example lives.|
location|Lisbon|Lisbon is where Carol Example lives.|
location|Barcelona|Barcelona is where Jack Example lives.|
location|Berlin|Berlin is a city Owner Example plans to visit.|
location|London|London is where Owner Example did a summer school.|
location|University Library|University Library is where Owner Example writes the thesis.|
skill|Debugging Async Python|Debugging Async Python is Owner Example's method for tracing event loop bugs.|
skill|Writing Design Docs|Writing Design Docs is how Owner Example plans features before coding.|
"""

#: (day, origin, title, [(speaker, text), ...]) — the person's turns and the agent's replies.
CONVERSATIONS = [
    ("2026-10-18", "claude-code", "Alpha Project storage move", [
        ("user", "I'm finally moving Alpha Project off PostgreSQL. Everything goes into SQLite now, one file per bank, and the vectors move from FAISS into sqlite-vec."),
        ("assistant", "That simplifies the install a lot. FastAPI stays as the backend? And the migration needs a script that copies the vectors."),
        ("user", "Yes, FastAPI stays. Carol is writing the migration script, she says the FAISS index can be re-embedded instead of copied."),
        ("assistant", "Re-embedding is cleaner. Which embedding model will you use for that?"),
        ("user", "The embedding model is EmbeddingGemma now, it runs locally. I want the Alpha Project MCP server to read from the same SQLite file so the agents see the same data."),
        ("assistant", "One file and one MCP server reading it keeps it consistent. Do you want a Claude Code plugin to install the MCP server?"),
        ("user", "Yes, a Claude Code plugin is the plan, so installing is one command. Entity resolution also has to move, it used Postgres trigram matching."),
        ("assistant", "In SQLite you can use FTS5 for the same matching."),
        ("user", "Good, FTS5 then. Carol will review the plugin next week."),
    ]),
    ("2026-10-18", "chatgpt", "Thesis reward model question", [
        ("user", "For my thesis I'm adding a learned reward model to the evaluation, the Atari benchmark alone doesn't show what I want."),
        ("assistant", "A learned reward model needs preference data. Do you train it with PPO afterwards?"),
        ("user", "Yes, the PPO algorithm from Stable Baselines, and the reward model is trained on Uma's preference dataset."),
        ("assistant", "Then the thesis evaluation compares PPO with the true reward and with the learned one?"),
        ("user", "Exactly. Dana wants the comparison in the literature review chapter too. By the way Dana is moving to Globex in January as a research scientist, she will still supervise me."),
        ("assistant", "Good that the supervision continues. Will you write the results in Overleaf as before?"),
        ("user", "Yes, Overleaf and LaTeX as before. I also want reward shaping as a baseline."),
        ("assistant", "Reward shaping is a sensible baseline next to the learned reward model."),
        ("user", "And I'll run everything on the GPU cluster, not Colab."),
    ]),
    ("2026-10-19", "claude-code", "Home server migration", [
        ("user", "I moved the Home Server off the Raspberry Pi onto the Mac Mini last weekend. Docker Compose files came over unchanged."),
        ("assistant", "The Mac Mini has a lot more headroom. Is Tailscale still how you reach it?"),
        ("user", "Yes, Tailscale still. I'm adding Home Assistant for the lights, which starts the Home Automation plan, and Pi-hole for ad blocking."),
        ("assistant", "Home Assistant and Pi-hole both run well in Docker. Do you need a reverse proxy?"),
        ("user", "Yes, I'm putting Nginx Proxy Manager in front of them with local certificates. Victor said that's easier than Traefik."),
        ("assistant", "Nginx Proxy Manager has a web UI, so it's simpler to maintain. What happens to the Raspberry Pi?"),
        ("user", "The Raspberry Pi becomes a backup target, it syncs to AWS S3 every night."),
    ]),
    ("2026-10-19", "chatgpt", "German course plans", [
        ("user", "I signed up for an evening German course at the Goethe Institut, it starts in November. Karen is the teacher."),
        ("assistant", "A structured course will help next to Duolingo. Will you keep Anki for vocabulary?"),
        ("user", "Yes, Anki with spaced repetition for the vocabulary, and I stopped Duolingo, it felt like a game more than learning."),
        ("assistant", "That's a common experience. Is the course for the Berlin trip?"),
        ("user", "Partly the Berlin trip in December, but mostly because I might apply for jobs in Berlin after the thesis."),
        ("assistant", "That gives the language learning a concrete goal."),
        ("user", "Yes. I use DeepL for checking my sentences."),
    ]),
    ("2026-10-19", "claude-code", "Waitlist and analytics", [
        ("user", "The waitlist page for Alpha Project is live on Vercel, it's part of the Personal Website now instead of a separate site."),
        ("assistant", "Merging it into the Personal Website keeps one deploy. Are sign-ups still stored in Supabase?"),
        ("user", "Yes Supabase. I'm adding Google Analytics to see where the visitors come from, and I need a privacy policy before that."),
        ("assistant", "Google Analytics needs a cookie notice in the EU as well. Do you want a privacy-friendly alternative?"),
        ("user", "Maybe Plausible Analytics instead, it doesn't need cookies. The page uses Tailwind CSS and follows the design system from the app."),
        ("assistant", "Plausible Analytics avoids the cookie banner. Tailwind CSS can read the design tokens directly."),
        ("user", "Nina will review the waitlist page design on Friday."),
    ]),
    ("2026-10-19", "chatgpt", "Hooli interview prep call", [
        ("user", "Call with Erin from Hooli today about the machine learning engineer role, the first round is a system design interview."),
        ("assistant", "A system design interview for ML usually asks for a training and serving pipeline. What did Erin say about the team?"),
        ("user", "The team works on the Hooli Cloud recommendations product. Frank, my friend with the studio, says a friend of his worked there."),
        ("assistant", "That could be a useful contact. Do you want to plan the interview preparation?"),
        ("user", "Yes, interview preparation two evenings a week. Grace Placeholder, a staff engineer there, will do a mock interview with me, Grace is a friend of Leo's."),
        ("assistant", "A mock interview with someone on the team is very valuable."),
        ("user", "I'll also review recommender systems, my capstone was on that, and linear algebra."),
    ]),
    ("2026-10-19", "claude-code", "Fine-tuning experiment", [
        ("user", "I'm running a LoRA fine-tuning experiment on a small language model with Hugging Face Transformers and PyTorch, for the workshop paper."),
        ("assistant", "What are you fine-tuning it for?"),
        ("user", "To write page summaries for Alpha Project. I need an evaluation harness that scores the summaries against the source conversations."),
        ("assistant", "An evaluation harness with a judge model is the usual approach. Where do you log runs?"),
        ("user", "Weights and Biases for logging, the lab's Weights Dashboard is too slow. Training runs on the GPU cluster, Google Colab was too small."),
        ("assistant", "Weights and Biases makes the comparison across runs easy. Do you compare with the base model?"),
        ("user", "Yes, model evaluation against the base model and against Claude API summaries. Iris wants the numbers by November for the research paper draft."),
    ]),
    ("2026-10-19", "chatgpt", "Notes and weekly review", [
        ("user", "I moved all my notes from Notion to Obsidian this month. Notion was too slow and I want plain markdown files."),
        ("assistant", "Obsidian keeps everything as local markdown. Will you keep project plans there too?"),
        ("user", "Yes, project plans and my journaling. I'm starting a weekly review on Sunday instead of the weekly planning I did before."),
        ("assistant", "A weekly review looks back as well as forward. Do you use templates?"),
        ("user", "A template with what I shipped, what's stuck, and the next week's time blocking. Deep work blocks in the morning after running."),
        ("assistant", "That fits your morning routine."),
        ("user", "And my second brain is basically Alpha Project now, Obsidian is just for writing."),
    ]),
]
