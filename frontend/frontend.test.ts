import { strict as assert } from "node:assert";
import { test } from "node:test";
import { displayMessage, isReply, isWorkspace, makeMessage, validMessage } from "./lib/client.ts";

test("validates reply phase and required fields", () => {
  const reply={session_id:"demo",message_id:"first",phase:"VERIFY_ID",session_status:"active",response:"Hello",next_expected_action:"ASK"};
  assert.equal(isReply(reply),true);
  assert.equal(isReply({...reply,phase:"APPROVED"}),false);
  assert.equal(isReply({...reply,response:{html:"invalid"}}),false);
});

test("rejects a partial workspace contract",()=>{
  assert.equal(isWorkspace({phase:"VERIFY_ID",status:"active"}),false);
});

test("validates composer length and redacts verification inputs",()=>{
  assert.equal(validMessage("   "),false);
  assert.equal(validMessage("x".repeat(4001)),false);
  assert.equal(validMessage("Claim status"),true);
  assert.equal(displayMessage("Private synthetic input","VERIFY_ID"),"Message submitted securely.");
  assert.equal(displayMessage("How much was paid?","PROCESS_CASE"),"How much was paid?");
  assert.notEqual(makeMessage("same").message_id,makeMessage("same").message_id);
});
