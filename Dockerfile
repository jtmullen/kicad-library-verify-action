FROM python:3-slim AS builder

COPY main.py /main.py

RUN apt-get update \
&& apt-get install -y --no-install-recommends git \
&& apt-get purge -y --auto-remove \
&& rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip
RUN pip3 install PyYAML==6.0
RUN pip3 install gitpython==3.1.27
RUN pip3 install actions_toolkit==0.1.13
RUN git clone https://github.com/jtmullen/kicad_parser.git \
&& cd kicad_parser \
&& git checkout fc8b0a56d70e0772f6f10915cbb4b4557b98d9a5 \
&& git submodule update --init

CMD ["/main.py"]
ENTRYPOINT ["python3"]