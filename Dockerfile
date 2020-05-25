FROM ubuntu:19.10

ENV DEBIAN_FRONTEND=noninteractive

RUN \
  apt-get update && apt-get install -y software-properties-common && \
  apt-get update && \
  apt-get install -y build-essential zlib1g-dev libnss3-dev libssl-dev libffi-dev wget vim supervisor nginx && \
  apt-get install -y python3.7 python3-pip && \
  ln -sf /usr/bin/python3.7 /usr/local/bin/python && \
  rm -rf /var/lib/apt/lists/* && \
  wget https://dl.influxdata.com/telegraf/releases/telegraf_1.13.3-1_amd64.deb && \
  dpkg -i telegraf_1.13.3-1_amd64.deb

COPY docker_files/nginx/default /etc/nginx/sites-available/default
COPY docker_files/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker_files/supervisord/* /etc/supervisor/conf.d/
COPY ./docker_files /home/dusr/code/docker_files

RUN \
  python3.7 -m pip install -r /home/dusr/code/docker_files/dependencies.pip

COPY . /home/dusr/code/

EXPOSE 80
WORKDIR /home/dusr/code

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
