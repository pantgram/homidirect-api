import { FastifyInstance } from "fastify";
import { UserController } from "./users.controller";

const userController = new UserController();

export async function userRoutes(fastify: FastifyInstance) {
  fastify.get("/users", userController.getAll.bind(userController));
  fastify.get("/users/:id", userController.getById.bind(userController));
  fastify.post("/users", userController.create.bind(userController));
  fastify.patch("/users/:id", userController.update.bind(userController));
  fastify.delete("/users/:id", userController.delete.bind(userController));
}
