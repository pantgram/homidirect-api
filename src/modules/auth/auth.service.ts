import { db } from "../../config/db";
import { users } from "../../modules/users/users.model";
import { eq } from "drizzle-orm";
import { hashPassword, comparePasswords } from "@/utils/hash";
import { signToken } from "@/utils/jwt";

export const AuthService = {
  async register({ email, password, firstName, lastName }: RegisterInput) {
    const [existing] = await db
      .select()
      .from(users)
      .where(eq(users.email, email));
    if (existing) throw new Error("Email already registered");

    const hashed = await hashPassword(password);
    const [user] = await db
      .insert(users)
      .values({
        email,
        password: hashed,
        firstName,
        lastName,
      })
      .returning();

    const token = signToken({ id: user.id, email: user.email });
    return { user, token };
  },

  async login({ email, password }: LoginInput) {
    const [user] = await db.select().from(users).where(eq(users.email, email));
    if (!user) throw new Error("Invalid credentials");

    const valid = await comparePasswords(password, user.password);
    if (!valid) throw new Error("Invalid credentials");

    const token = signToken({ id: user.id, email: user.email });
    return token;
  },
};
