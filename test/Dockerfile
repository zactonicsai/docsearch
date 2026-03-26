FROM alpine:3.21
RUN apk add --no-cache bash curl
COPY integration_test.sh /test/integration_test.sh
RUN chmod +x /test/integration_test.sh
WORKDIR /test
CMD ["/test/integration_test.sh"]
