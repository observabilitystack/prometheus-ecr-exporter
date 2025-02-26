FROM python:3.9-alpine

# Install app code
RUN mkdir /app
ADD ./setup.* README.md /app/
ADD ecr_exporter /app/ecr_exporter
ADD tests /app/tests

# Install app deps
RUN cd /app && pip install -e .

# Run as non-root
RUN adduser app -S -u 1000
USER app

# Switch the cwd to /app so that running app and tests is easier
WORKDIR /app

ENV AWS_DEFAULT_REGION eu-central-1
CMD [ "ecr_exporter" ]
