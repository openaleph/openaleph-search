FROM elasticsearch:9.1.1

RUN bin/elasticsearch-plugin install --batch analysis-icu

ADD --chmod=644 https://raw.githubusercontent.com/opensanctions/rigour/refs/heads/main/rust/data/names/person_names.txt /tmp/person_names.txt
RUN sed 's/ => .*//' /tmp/person_names.txt > /usr/share/elasticsearch/config/person_name_synonyms.txt
