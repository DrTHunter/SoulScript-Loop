FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        sudo ca-certificates curl wget git nano vim less tmux htop jq ripgrep unzip zip sqlite3 \
        build-essential python3 python3-pip python3-venv nodejs npm iproute2 iputils-ping dnsutils tini \
    && rm -rf /var/lib/apt/lists/*

# Who she is on this machine. Build with --build-arg AGENT_USER=name to rename her.
ARG AGENT_USER=agent
# Passwordless sudo is a decision, not a default. 0 = none (she works in her home, pip --user, venvs);
# 1 = full root inside the container (apt install, system changes).
ARG AGENT_SUDO=0
ENV AGENT_USER=${AGENT_USER}

# ubuntu:24.04 ships a uid-1000 'ubuntu' user: drop it so the agent gets 1000.
RUN userdel -r ubuntu 2>/dev/null || true \
    && useradd -m -u 1000 -s /bin/bash ${AGENT_USER} \
    && if [ "${AGENT_SUDO}" = "1" ]; then \
         echo "${AGENT_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${AGENT_USER} && chmod 440 /etc/sudoers.d/${AGENT_USER}; \
       fi

COPY server.py start.sh /opt/machine/
COPY home-README.md /opt/machine/README.md
RUN chmod +x /opt/machine/start.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
# tini is PID 1 so the processes she leaves behind are reaped instead of piling up as zombies.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/machine/start.sh"]
