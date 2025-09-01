import Fastify from "fastify";

const app = Fastify({
  logger: true,
});

// Declare a route
app.get("/", function (request, reply) {
  reply.send({ hello: "world" });
});

// Run the server!
app.listen({ port: 3000, host: "127.0.0.1" }, function (err, address) {
  if (err) {
    app.log.error(err);
    process.exit(1);
  }
  app.log.info(`server listening on ${address}`);
});
