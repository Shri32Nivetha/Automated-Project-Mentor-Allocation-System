import { describe, expect, it } from "vitest";
import { emailError } from "../email.js";

describe("institutional e-mail (frontend)", () => {
  it("accepts any username on @srmist.edu.in, after normalisation", () => {
    for (const v of ["ab1234@srmist.edu.in", " Any.Name+1@SRMIST.EDU.IN ", "x_y-z@srmist.edu.in"]) expect(emailError(v)).toBeNull();
  });
  it("rejects external domains", () => {
    for (const v of ["a@gmail.com", "a@yahoo.com", "a@outlook.com", "a@srmist.edu", "a@mail.srmist.edu.in", "a@srmist.edu.in.evil.com"])
      expect(emailError(v)).toMatch(/@srmist\.edu\.in/);
  });
  it("rejects invalid formats", () => {
    for (const v of ["", "plain", "a@", "@srmist.edu.in", "a b@srmist.edu.in"]) expect(emailError(v)).toBeTruthy();
  });
});
