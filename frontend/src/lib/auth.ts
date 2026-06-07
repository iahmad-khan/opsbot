import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "OpsBot Dashboard",
      credentials: {
        password: { label: "Dashboard Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.password) return null;
        const apiUrl = process.env.API_URL || "http://localhost:8000";
        try {
          const res = await fetch(`${apiUrl}/api/auth/token`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: credentials.password }),
            cache: "no-store",
          });
          if (!res.ok) return null;
          const data = await res.json();
          return {
            id: "dashboard",
            name: "OpsBot Admin",
            accessToken: data.access_token,
          };
        } catch {
          return null;
        }
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60, // 24 h
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.accessToken = (user as any).accessToken;
      return token;
    },
    async session({ session, token }) {
      (session as any).accessToken = token.accessToken;
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET || process.env.SECRET_KEY || "change-me",
};
