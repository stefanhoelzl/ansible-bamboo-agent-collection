FROM python:3

COPY --chown=root ssh_key.priv /root/.ssh/id_rsa
RUN chmod 0700 /root/.ssh/id_rsa

RUN pip install ansible==2.9.5
RUN mkdir /project
WORKDIR /project
