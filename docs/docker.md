# Docker

## Build and run the image

```bash
git clone https://github.com/ratoaq2/homebuddy.git
cd homebuddy
docker build -t homebuddy .
docker run --rm -p 8080:8080 --env-file .env \
    -v ./homebuddy.yml:/home/homebuddy/homebuddy.yml:ro homebuddy
```

The image starts the page on port 8080. The image does not contain the `.env` file or the configuration file.

- Give the token with `--env-file` or with `-e HA_TOKEN=...`.
- Mount the configuration file at `/home/homebuddy/homebuddy.yml`.

The process in the image is not `root`.

The image listens on each network interface, and the page has no login. With `-p 8080:8080`, each device on
your network can open the page. Use this command only on a network you trust.

## Docker Compose

```yaml
services:
  homebuddy:
    build: .
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    env_file: .env
    volumes:
      - ./homebuddy.yml:/home/homebuddy/homebuddy.yml:ro
```

## Put homebuddy behind a reverse proxy

A reverse proxy adds a login and HTTPS to the page. First, let only the computer of the container connect to
homebuddy:

```bash
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env \
    -v ./homebuddy.yml:/home/homebuddy/homebuddy.yml:ro homebuddy
```

Then put a reverse proxy with a login on the same computer. This example is a `Caddyfile` for
[Caddy](https://caddyserver.com/) 2.8 or later:

```
homebuddy.example.com {
    basic_auth {
        # The command "caddy hash-password" makes the hash of a password.
        your-name your-password-hash
    }
    reverse_proxy 127.0.0.1:8080
}
```

Caddy gets a certificate for the host name. The page uses a WebSocket. Caddy passes it without more settings.
A different reverse proxy can need a setting for it.
