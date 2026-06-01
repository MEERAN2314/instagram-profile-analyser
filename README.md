# Instagram Profile Analyser 📊

A premium, highly animated web application built with **FastAPI**, **Jinja2**, and **MongoDB Atlas** for bulk-collecting, tracking, and cache-managing Instagram public profile metrics (Followers, Following, and Posts count).

---

## Features 🚀

- **Bulk Username Submission**: Paste multiple Instagram usernames (separated by spaces, commas, or newlines) directly into a spacious form box.
- **Three-Tiered Scraping Pipeline**:
  - **Tier 1: Instaloader Engine** (Direct live Instagram fetch wrapped in non-blocking thread executors).
  - **Tier 2: DuckDuckGo Snippet Scraper** (Resilient search engine scrapers when Instagram live blocks occur).
  - **Tier 3: Smart Simulation Engine** (A custom high-fidelity toggle to generate realistic metrics instantly without network blocks, ensuring perfect demo capability).
- **Premium Blue & White UI**: A modern interface styled using the **Outfit** Google Font and **Lucide Icons** (15+ vector thin-line icons, completely emoji-free).
- **SSE Live Progress Tracker**: A glassmorphic progress dialog overlay displaying active crawling target counts, shimmering progress bars, and scrolling colored log terminals via **Server-Sent Events**.
- **Interactive Tables**: Client-side instant keyword search and column sort indicators (sort by followers, following, posts, status, check-times).
- **Asynchronous Inline Updates**: One-click actions to instantly refresh metrics for a single profile (triggering shimmering cell loaders) or fade-delete rows from the database.
- **Data Exporting**: Instant downloads for cached data in **CSV** and **JSON** formats.

---

## Technical Stack 🛠️

- **Backend**: Python 3.10+, FastAPI (Asynchronous High-Performance framework)
- **Database**: MongoDB Atlas / Local MongoDB (utilizing `motor` for asynchronous driver operations and `pymongo`)
- **Scraper Client**: Instaloader (Live client) & HTTPX (for async search-engine queries)
- **Frontend**: Jinja2 Server-side rendering, Vanilla CSS variables, and Vanilla JavaScript.

---

## Installation & Setup 💻

### 1. Clone & Enter Directory
Ensure you are in the project folder:
```bash
cd "instagram-profile-analyser"
```

### 2. Establish Virtual Environment
Create a clean environment and activate it:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
Install all requirements from the list:
```bash
pip install -r requirements.txt
```

### 4. Setup MongoDB Atlas Connection
Create a `.env` file in the root directory:
```env
MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
```
*(If no `.env` is supplied or the variable is omitted, the app will automatically fall back to local `mongodb://localhost:27017`.)*

### 5. Start the Application
Run the local uvicorn server in reload mode:
```bash
uvicorn main:app --reload
```

Open your browser to **`http://127.0.0.1:8000`** and enjoy the professional experience!
