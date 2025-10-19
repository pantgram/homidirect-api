import "fastify";

declare module "fastify" {
  interface FastifyInstance {
    config: {
      SUPABASE_URL: string;
      SUPABASE_SERVICE_KEY: string;
      DATABASE_URL: string;
      PORT: string;
    };
  }
}
