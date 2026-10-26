#!/data/data/com.termux/files/usr/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

LOG_DIR="$HOME/paywaveke-backend/logs"
mkdir -p "$LOG_DIR"
WORKER_LOG="$LOG_DIR/celery_worker.log"
BEAT_LOG="$LOG_DIR/celery_beat.log"

echo -e "${YELLOW}🚀 Starting PayWaveKE...${NC}"

# 1. Redis (required locally)
if ! pgrep -x "redis-server" > /dev/null; then
    echo -e "${GREEN}▶ Starting Redis...${NC}"
    redis-server --daemonize yes
    sleep 1
else
    echo -e "${GREEN}✓ Redis already running${NC}"
fi

# 2. Celery Worker
echo -e "${GREEN}▶ Starting Celery Worker...${NC}"
celery -A core worker --loglevel=info > "$WORKER_LOG" 2>&1 &
CELERY_WORKER_PID=$!

# 3. Celery Beat
echo -e "${GREEN}▶ Starting Celery Beat...${NC}"
celery -A core beat --loglevel=info > "$BEAT_LOG" 2>&1 &
CELERY_BEAT_PID=$!

cleanup() {
    echo -e "${YELLOW}🛑 Shutting down PayWaveKE...${NC}"
    kill $CELERY_WORKER_PID 2>/dev/null
    kill $CELERY_BEAT_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo -e "${GREEN}▶ Starting Django server...${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN} Database: Neon PostgreSQL (cloud)${NC}"
echo -e "${GREEN} Redis:    localhost:6379${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
python manage.py runserver
