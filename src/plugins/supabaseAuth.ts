import fp from "fastify-plugin";
import { FastifyRequest, FastifyReply } from "fastify";
import { createRemoteJWKSet, jwtVerify } from "jose";

export interface SupabaseUser {
  sub: string; // Supabase user ID
  email?: string; // Supabase email (if provided)
  [key: string]: any;
}

declare module "fastify" {
  interface FastifyRequest {
    user?: SupabaseUser;
  }
}

export default fp(async (fastify) => {
  // Your Supabase project URL
  const SUPABASE_URL = process.env.SUPABASE_URL!;
  const JWKS_URL = `${SUPABASE_URL}/auth/v1/jwks`;

  // Remote JWKS for verifying Supabase JWTs
  const JWKS = createRemoteJWKSet(new URL(JWKS_URL));

  fastify.decorate(
    "authenticate",
    async (request: FastifyRequest, reply: FastifyReply) => {
      try {
        const authHeader = request.headers.authorization;
        if (!authHeader) {
          return reply
            .status(401)
            .send({ error: "Missing Authorization header" });
        }

        const token = authHeader.split(" ")[1];
        if (!token) {
          return reply
            .status(401)
            .send({ error: "Invalid Authorization header format" });
        }

        const { payload } = await jwtVerify(token, JWKS, {
          issuer: `${SUPABASE_URL}/auth/v1`,
        });

        request.user = payload as SupabaseUser;
      } catch (err) {
        request.log.error(err);
        return reply.status(401).send({ error: "Unauthorized" });
      }
    }
  );
});
