FROM elasticsearch:9.3.3 AS base

RUN bin/elasticsearch-plugin install --batch analysis-icu

FROM base AS full

ADD --chmod=644 https://raw.githubusercontent.com/opensanctions/rigour/refs/heads/main/rust/data/names/person_names.txt /tmp/person_names.txt
RUN sed 's/ => .*//' /tmp/person_names.txt > /usr/share/elasticsearch/config/person_name_synonyms.txt

FROM base AS test

COPY tests/fixtures/person_name_synonyms.txt /usr/share/elasticsearch/config/person_name_synonyms.txt
