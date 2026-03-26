FROM golang:1.23-alpine AS builder

RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

# Copy source first, then tidy to generate go.sum from scratch
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=1 GOOS=linux go build -o /docms-server ./cmd/main.go

FROM alpine:3.21
RUN apk add --no-cache ca-certificates sqlite-libs curl
COPY --from=builder /docms-server /usr/local/bin/docms-server

RUN mkdir -p /data/uploads

EXPOSE 8080
CMD ["docms-server"]
