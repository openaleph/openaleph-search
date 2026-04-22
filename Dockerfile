FROM elasticsearch:9.3.3

RUN bin/elasticsearch-plugin install mapper-annotated-text \
    && bin/elasticsearch-plugin install --batch analysis-icu
