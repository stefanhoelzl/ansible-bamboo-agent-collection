#/bin/bash
set -x

# docker cleanup
docker kill testenv_agent_1 testenv_server_1 testenv_ansible_1
docker rm testenv_agent_1 testenv_server_1 testenv_ansible_1
docker network rm testenv_internal testenv_default

set -e

# server cleanup
rm -Rf server/data
tar -xzvf server/init-data.tar.gz -C server

# ansible cleanup and preperation
rm -rf ansible/project/library ansible/project/results
mkdir -p ansible/project/library ansible/project/results
cp ../bamboo-agent-configuration.py ansible/project/library

# run test environment
docker-compose up --build
