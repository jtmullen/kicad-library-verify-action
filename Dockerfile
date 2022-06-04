FROM alpine:3.10

COPY main.py /main.py

RUN apk --no-cache add git
RUN apk add python3
RUN apk add py3-pip
RUN python3 -m pip install -r requirements.txt
RUN git clone https://github.com/jtmullen/kicad_parser.git \
&& cd kicad_parser \
&& git checkout fc8b0a56d70e0772f6f10915cbb4b4557b98d9a5 \
&& git submodule update --init

CMD ["/main.py"]
ENTRYPOINT ["python3"]