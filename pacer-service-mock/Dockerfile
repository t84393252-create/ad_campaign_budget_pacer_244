FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY main.go .
RUN go build -o pacer-service main.go

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/
COPY --from=builder /app/pacer-service .
EXPOSE 8080
CMD ["./pacer-service"]