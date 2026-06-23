FROM debian:12.14-slim
# Copy application files
COPY . /app
# Install required system packages
RUN apt-get update && apt-get -y install curl gnupg vim ssh && apt-get clean \
    && rm -rf /var/lib/apt/lists/* 
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.5/install.sh | bash -

EXPOSE 80
CMD ["npm", "start", "--prefix", "app"]