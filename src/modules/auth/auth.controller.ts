import { FastifyReply, FastifyRequest } from "fastify";
import { AuthService } from "./auth.service";

export const AuthController = {
  async register(req: FastifyRequest, reply: FastifyReply) {
    try {
      const { email, password, firstName, lastName } = req.body as any;
      const data = await AuthService.register({
        email,
        password,
        firstName,
        lastName,
      });
      reply.status(201).send(data);
    } catch (err: any) {
      reply.status(400).send({ message: err.message });
    }
  },

  async login(req: FastifyRequest, reply: FastifyReply) {
    try {
      const { email, password } = req.body as any;
      const token = await AuthService.login({ email, password });
      reply.send({ token });
    } catch (err: any) {
      reply.status(401).send({ message: err.message });
    }
  },

  async me(req: FastifyRequest, reply: FastifyReply) {
    reply.send(req.user);
  },
};
