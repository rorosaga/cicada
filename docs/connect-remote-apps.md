# Add Cicada to claude.ai or ChatGPT (web and phone)

Cicada runs on your Mac (or your server). claude.ai and ChatGPT run in the cloud, so they reach your memory through
one public address that **you** open, to one port only: Cicada's remote connector (`8765`), which serves nothing but
the memory tools and the sign-in. The app signs in, you approve it in Cicada, and from then on every conversation in
that app is kept as it happens (ruling 32). How it works and what it checks: `docs/architecture/network.md`
("Sign-in for the remote connector").

## 1. Turn it on

Cicada → Settings → Agents → **From anywhere** → *Let AI apps outside this Mac use your memory*.

## 2. Give it a stable public address (you run this, Cicada never does)

Pick one. Both forward only port `8765`.

- **Tailscale Funnel** (free; the address is your machine's name, so it stays the same):

  ```sh
  tailscale funnel --bg 8765
  ```

  Your address is `https://<machine>.<tailnet>.ts.net`. Renaming the machine changes it.
- **ngrok** with your account's free static domain (a random ngrok address changes on every restart, and the app
  would lose Cicada each time):

  ```sh
  ngrok http 8765 --url https://<your-static-domain> --inspect=false
  ```

Never funnel or forward port `8000` — that is the full API, and it stays on this machine (and your tailnet) only.
Back in **From anywhere**, *How apps reach this Mac* should say **Reachable at** your address; if Cicada didn't detect
it, paste it under *I have my own HTTPS address*.

## 3. Add it to the app

Your server URL is your address plus `/mcp`, for example `https://<machine>.<tailnet>.ts.net/mcp`.

- **claude.ai** (Free allows one custom connector; Pro, Max, Team and Enterprise more): Customize → Connectors →
  **+ Add** → *Add custom connector* → name it Cicada, paste the URL → keep the detected sign-in (OAuth) → **Add**,
  then connect. Once added on your account it works in the Claude desktop, iOS and Android apps too.
- **ChatGPT**: chatgpt.com/plugins → **+** → *Add custom MCP server* → name and description → Connection: *Public
  endpoint*, paste the URL → Authentication: OAuth → *I understand and want to continue* → *Create as a plugin*. Start
  a new conversation and pick Cicada with `@`. ChatGPT asks before each tool that writes; for capture, allow it always.

## 4. Type the code into Cicada

The app opens a Cicada page showing an eight-character code. On your Mac, **From anywhere** says *A sign-in is
waiting*: type that code and press **Find**. Cicada shows who it is (an app that only registered itself is shown as
*Unverified app*, whatever it calls itself) and where it returns — check it is `claude.ai` or `chatgpt.com` — then
choose what it may do (search, read and record are the defaults; *record* includes keeping each conversation) and when
it expires (7, 30 or 90 days), and **Approve**. The app's page moves on by itself. Only the code on your own page can
approve a sign-in, so a request someone else started cannot be approved by mistake; if you see requests you didn't
start, **Deny all**. Nothing is typed into the public page: no password exists there to steal.

On a server with no app, approve from the server itself — see `docs/architecture/headless.md` ("Sign-in on a server
with no app").

## 5. What happens next

- Each conversation becomes one episode, written turn by turn, marked as relayed by that app. Cicada does not count a
  relayed message as your own words when it decides what deserves a page or answers its own questions, because the
  app's model passed it on; an export of that app's conversations, imported later, replaces the relayed copy with
  your exact words.
- The app renews its own access. To end it, **Revoke** it under *Connectors* — it stops at once.
- The older secret link (`…/c/<token>/mcp`, from *New connector*) still works for apps without sign-in; prefer
  sign-in where the app supports it, since a link is a password in a URL.
