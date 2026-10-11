# Playwright's browser server, with its CLI baked in so the container starts
# without fetching anything from npm.
FROM mcr.microsoft.com/playwright:v1.63.0-noble
RUN npm install -g playwright@1.63.0 && npm cache clean --force
USER pwuser
WORKDIR /home/pwuser
CMD ["playwright", "run-server", "--port", "3000", "--host", "0.0.0.0"]
