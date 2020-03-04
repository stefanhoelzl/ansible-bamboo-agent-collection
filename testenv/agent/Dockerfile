FROM atlassian/bamboo-agent-base:6.9.2

# enable ssh
USER root
RUN apt-get update \
    && apt-get install -y sudo openssh-server \
    && echo ${BAMBOO_USER} ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/${BAMBOO_USER}\
    && chmod 0440 /etc/sudoers.d/${BAMBOO_USER}
USER ${BAMBOO_USER}
COPY --chown=${BAMBOO_USER} ssh_key.pub /home/bamboo/.ssh/authorized_keys
RUN chmod 0700 /home/bamboo/.ssh/
RUN chmod 0640 /home/bamboo/.ssh/authorized_keys
RUN sed '2 i sudo service ssh start' runAgent.sh | tee runAgent.sh
EXPOSE 22
