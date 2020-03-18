#/bin/bash
set -ex
cd `dirname $0`/env

# cleanup
git clean -fdx

# prepare server application data
tar -xzvf server/init-data.tar.gz -C server
chmod -R 0777 server/data

# ansible cleanup and preperation
mkdir -p results
chmod 0777 results
python3 playbook.py ansible/project/playbook.json
../../build.sh
ansible-galaxy collection install ../../release/stefanhoelzl-bamboo_agent* -p ./ansible/project/collections
ANSIBLE_COLLECTIONS_PATHS=./ansible/project/collections ansible-playbook ansible/project/playbook.json --syntax-check

# run test environment
docker-compose down
docker-compose up --build --abort-on-container-exit
docker-compose logs ansible > results/ansible.logs
docker-compose logs server > results/server.logs
docker-compose logs agent > results/agent.logs
docker-compose down

# check results
python3 playbook.py

# successfully finished when arrived here
echo "acceptance tests finished successfully"
