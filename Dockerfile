FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod tidy
COPY main.go .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /phonelink-server .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /phonelink-server /usr/local/bin/phonelink-server
RUN mkdir -p /app/data
EXPOSE 8765 8766
CMD ["phonelink-server", "--forward", "--data-dir", "/app/data"]
