import { FastifyInstance } from "fastify";
import { createClient } from "@supabase/supabase-js";

export default async function authRoutes(fastify: FastifyInstance) {
  const supabase = createClient(
    process.env.SUPABASE_URL as string,
    process.env.SUPABASE_SERVICE_KEY as string
  );

  // Signup
  fastify.post("/signup", async (request, reply) => {
    const { email, password } = request.body as {
      email: string;
      password: string;
    };

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
    });

    if (error) {
      return reply.status(400).send({ error: error.message });
    }

    return reply.send({ user: data.user });
  });

  // Login
  fastify.post("/login", async (request, reply) => {
    const { email, password } = request.body as {
      email: string;
      password: string;
    };

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      return reply.status(400).send({ error: error.message });
    }

    return reply.send({
      user: data.user,
      session: data.session, // contains access_token + refresh_token
    });
  });

  // Refresh token
  fastify.post("/refresh", async (request, reply) => {
    const { refresh_token } = request.body as { refresh_token: string };

    const { data, error } = await supabase.auth.refreshSession({
      refresh_token,
    });

    if (error) {
      return reply.status(400).send({ error: error.message });
    }

    return reply.send({
      user: data.user,
      session: data.session,
    });
  });

  // Logout
  fastify.post("/logout", async (request, reply) => {
    const { access_token } = request.body as { access_token: string };

    const { error } = await supabase.auth.admin.signOut(access_token);

    if (error) {
      return reply.status(400).send({ error: error.message });
    }

    return reply.send({ success: true });
  });
}
