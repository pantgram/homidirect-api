import { FastifyRequest, FastifyReply } from "fastify";
import { UserService } from "./users.service";
import { CreateUserDTO, UpdateUserDTO } from "./users.types";

const userService = new UserService();

export class UserController {
  async getAll(request: FastifyRequest, reply: FastifyReply) {
    try {
      const users = await userService.getAllUsers();
      return reply.code(200).send({ data: users });
    } catch (error) {
      return reply.code(500).send({ error: "Internal server error" });
    }
  }

  async getById(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ) {
    try {
      const id = parseInt(request.params.id);
      const user = await userService.getUserById(id);

      if (!user) {
        return reply.code(404).send({ error: "User not found" });
      }

      return reply.code(200).send({ data: user });
    } catch (error) {
      return reply.code(500).send({ error: "Internal server error" });
    }
  }

  async create(
    request: FastifyRequest<{ Body: CreateUserDTO }>,
    reply: FastifyReply
  ) {
    try {
      const user = await userService.createUser(request.body);
      return reply.code(201).send({ data: user });
    } catch (error) {
      return reply.code(500).send({ error: "Internal server error" });
    }
  }

  async update(
    request: FastifyRequest<{ Params: { id: string }; Body: UpdateUserDTO }>,
    reply: FastifyReply
  ) {
    try {
      const id = parseInt(request.params.id);
      const user = await userService.updateUser(id, request.body);

      if (!user) {
        return reply.code(404).send({ error: "User not found" });
      }

      return reply.code(200).send({ data: user });
    } catch (error) {
      return reply.code(500).send({ error: "Internal server error" });
    }
  }

  async delete(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ) {
    try {
      const id = parseInt(request.params.id);
      const deleted = await userService.deleteUser(id);

      if (!deleted) {
        return reply.code(404).send({ error: "User not found" });
      }

      return reply.code(204).send();
    } catch (error) {
      return reply.code(500).send({ error: "Internal server error" });
    }
  }
}
