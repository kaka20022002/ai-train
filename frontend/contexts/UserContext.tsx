"use client";

import {
  createContext, useCallback, useContext,
  useEffect, useState, type ReactNode,
} from "react";
import { usersApi } from "@/lib/api";
import type { UserProfile } from "@/lib/api";
import { DEMO_USER_ID } from "@/lib/constants";

const STORAGE_KEY = "ai_train_user_id";

interface UserContextValue {
  userId: string;
  setUserId: (id: string) => void;
  profile: UserProfile | null;
  profileLoading: boolean;
  refreshProfile: () => Promise<void>;
}

const UserContext = createContext<UserContextValue | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [userId, setUserIdState] = useState(DEMO_USER_ID);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  // Restore from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setUserIdState(stored);
  }, []);

  const setUserId = useCallback((id: string) => {
    setUserIdState(id);
    localStorage.setItem(STORAGE_KEY, id);
  }, []);

  const refreshProfile = useCallback(async () => {
    setProfileLoading(true);
    try {
      const p = await usersApi.get(userId);
      setProfile(p);
    } catch {
      setProfile(null);
    } finally {
      setProfileLoading(false);
    }
  }, [userId]);

  useEffect(() => { refreshProfile(); }, [refreshProfile]);

  return (
    <UserContext.Provider value={{ userId, setUserId, profile, profileLoading, refreshProfile }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
