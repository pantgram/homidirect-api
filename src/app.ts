import Fastify from "fastify";
import supabaseAuth from "./plugins/supabaseAuth";
import dotenv from "dotenv";
import authRoutes from "./routes/auth/auth.routes";
async function buildServer() {
  dotenv.config(); // <-- loads .env into process.env
  const app = Fastify({ logger: true });

  // Register Supabase auth plugin
  await app.register(supabaseAuth);

  // Health check
  app.get("/health", async () => ({ status: "ok" }));
  app.register(authRoutes, { prefix: "/auth" });

  // Register routes

  return app;
}

if (require.main === module) {
  (async () => {
    const app = await buildServer();
    const port = process.env.PORT ? Number(process.env.PORT) : 3000;
    await app.listen({ port, host: "0.0.0.0" });
    console.log(`🚀 Server running at http://localhost:${port}`);
  })();
}

export default buildServer;
