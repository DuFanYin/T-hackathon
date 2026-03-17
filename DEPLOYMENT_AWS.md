## Deployment: AWS backend + Vercel frontend

### 1. Backend on AWS (EC2)

1. **Create EC2 instance**
   - Linux, small instance type, with a public IP.
   - Security group: allow SSH (22) from your IP; allow API port (e.g. 8000) from your IP or from the internet for testing.

2. **Install system dependencies**
   ```bash
   sudo apt update
   sudo apt install -y git python3 python3-venv
   ```

3. **Clone repo and create virtual env**
   ```bash
   git clone <your-repo-url>
   cd T-hackathon
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Create `.env` at repo root**
   ```env
   General_Portfolio_Testing_API_KEY='your_api_key'
   General_Portfolio_Testing_API_SECRET='your_api_secret'

   Competition_API_KEY='your_api_key'
   Competition_API_SECRET='your_api_secret'

   CONTROL_HOST=0.0.0.0
   CONTROL_PORT=8000
   CONTROL_CORS_ORIGINS='https://<your-vercel-app>.vercel.app'
   ```

5. **Start backend control API**
   ```bash
   source .venv/bin/activate
   python api_server.py mock   # or: python api_server.py real
   ```

### 2. Frontend on Vercel

1. **Push repo to GitHub / GitLab**

2. **Create Vercel project**
   - Import the repository.
   - Root Directory: `frontend`
   - Build Command: `npm run build`
   - Output Directory: `dist`

3. **Set environment variable on Vercel**
   - In Project → Settings → Environment Variables:
     - `VITE_API_BASE = http://<EC2-public-IP-or-domain>:8000`

4. **Deploy**
   - Trigger a deployment (or let Vercel auto-deploy on push).

### 3. End-to-end check

1. Open the Vercel URL, e.g. `https://your-app.vercel.app`.
2. In the sidebar, confirm the API address matches `VITE_API_BASE`.
3. Use the engine controls in the sidebar (Mock / Live / Stop) and verify:
   - Backend logs show activity.
   - Dashboard status updates.
4. Open the `Strategies`, `Symbols`, and `Logs` tabs and confirm:
   - Data loads correctly.
   - Logs stream in real time.

