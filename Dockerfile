FROM ubuntu:18.04

ENV DEBIAN_FRONTEND=noninteractive
RUN \
  apt-get update && apt-get install -y software-properties-common && \
  add-apt-repository ppa:deadsnakes/ppa && apt-get update && \
  apt-get install -y build-essential zlib1g-dev libnss3-dev libssl-dev libffi-dev wget vim supervisor nginx && \
  apt-get install -y python3.7 python3-pip && \
  ln -sf /usr/bin/python3.7 /usr/local/bin/python && \
  rm -rf /var/lib/apt/lists/*

COPY docker_files/nginx/default /etc/nginx/sites-available/default
COPY docker_files/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker_files/supervisord/* /etc/supervisor/conf.d/
COPY ./docker_files /home/dusr/code/docker_files

RUN \
  pip3 install -r /home/dusr/code/docker_files/dependencies.pip

COPY . /home/dusr/code/

EXPOSE 80
WORKDIR /home/dusr/code

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
