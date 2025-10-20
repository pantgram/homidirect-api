import { eq } from "drizzle-orm";
import { db } from "../../config/db";
import { users, NewUser } from "./users.model";
import { CreateUserDTO, UpdateUserDTO, UserResponse } from "./users.types";

export class UserService {
  async getAllUsers(): Promise<UserResponse[]> {
    const allUsers = await db
      .select({
        id: users.id,
        firstName: users.firstName,
        lastName: users.lastName,
        email: users.email,
        createdAt: users.createdAt,
      })
      .from(users);

    return allUsers;
  }

  async getUserById(id: number): Promise<UserResponse | null> {
    const [user] = await db
      .select({
        id: users.id,
        firstName: users.firstName,
        lastName: users.lastName,
        email: users.email,
        createdAt: users.createdAt,
      })
      .from(users)
      .where(eq(users.id, id))
      .limit(1);

    return user || null;
  }

  async createUser(data: NewUser): Promise<UserResponse> {
    const [newUser] = await db.insert(users).values(data).returning({
      id: users.id,
      firstName: users.firstName,
      lastName: users.lastName,
      email: users.email,
      createdAt: users.createdAt,
    });

    return newUser;
  }

  async updateUser(
    id: number,
    data: UpdateUserDTO
  ): Promise<UserResponse | null> {
    const [updatedUser] = await db
      .update(users)
      .set({ ...data, updatedAt: new Date() })
      .where(eq(users.id, id))
      .returning({
        id: users.id,
        firstName: users.firstName,
        lastName: users.lastName,
        email: users.email,
        createdAt: users.createdAt,
      });

    return updatedUser || null;
  }

  async deleteUser(id: number): Promise<boolean> {
    const result = await db
      .delete(users)
      .where(eq(users.id, id))
      .returning({ id: users.id });

    return result.length > 0;
  }
}
