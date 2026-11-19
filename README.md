# ❄️ Snowman Dance — Couple's Rhythm Game ❄️

A real-time, synchronized couple's rhythm web game built with FastAPI, WebSockets, HTML5 Canvas, and romantic winter animations.

---

## 🎮 Play Live Now!

👉 **[Play Snowman Dance Online](https://web-production-53fae433.up.railway.app)**

> **Live Deployment URL:**  
> `https://web-production-53fae433.up.railway.app`  
> *(Hosted 24/7 on Railway in the cloud — accessible on any mobile, tablet, or desktop browser).*

---

## ✨ Features

- **Real-Time Synchronized Dancing**: Two players connect in a shared room via WebSockets and dance synchronously.
- **Complementary Move Pairs**:
  - **Reach Out** (Boy) + **Take Hand** (Girl)
  - **Spin Her** (Boy) + **Twirl** (Girl)
  - **Dip** (Boy) + **Lean Back** (Girl)
- **10-Second Countdown Rounds**: Strict server-timed rounds to coordinate and sync moves with your partner.
- **Heartbeat Vibe Meter**: Each complementary match increases the Vibe meter by +20%; mismatches reduce it by -10%. Reach 100% to win!
- **Love Letters & Notes**: Compose and exchange warm letters directly with your partner in-game.
- **Persistent Audio Control**: Music and sound effects stay reliably muted/unmuted based on your preference across rounds.
- **Infinite Concurrent Rooms**: Anyone can open the main link and play in an automatically generated private room without colliding with other couples.

---

## 🕹️ How to Play

1. Open **[https://web-production-53fae433.up.railway.app](https://web-production-53fae433.up.railway.app)** in your browser.
2. Click **"Copy Invite Link"** and send it to your partner.
3. One player picks **Boy (Left)** and the other picks **Girl (Right)**.
4. Both players click **Ready!** to start the music and dancing.
5. In each 10-second round, pick complementary dance moves together to raise your Vibe to 100%!
6. Once you win, exchange winter notes in the mailbox and click **Play Again** to dance another round!

---

## 🛠️ Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn, WebSockets
- **Frontend**: Vanilla JavaScript, HTML5 Canvas, CSS3 Keyframe Animations
- **Deployment**: Railway (Nixpacks / Procfile)
