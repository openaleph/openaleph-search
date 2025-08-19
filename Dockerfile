FROM elasticsearch:9.1.1

RUN bin/elasticsearch-plugin install mapper-annotated-text
