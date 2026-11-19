import asyncio
import json
import websockets

async def test_full_game_with_system_room():
    room_id = "arctic-waltz-77"
    uri_base = f"ws://localhost:8000/ws/{room_id}"
    
    print(f"Connecting Boy (Jack) to system room: {room_id}")
    ws_boy = await websockets.connect(f"{uri_base}/p_boy")
    
    # Boy connected
    conn_boy = json.loads(await ws_boy.recv())
    assert conn_boy["type"] == "connected"
    
    # Register Boy
    await ws_boy.send(json.dumps({"type": "register", "name": "Jack", "role": "boy"}))
    reg_boy = json.loads(await ws_boy.recv())
    assert reg_boy["type"] == "registered"
    print("Boy registered!")

    # Girl connected
    print(f"Connecting Girl (Rose) to system room: {room_id}")
    ws_girl = await websockets.connect(f"{uri_base}/p_girl")
    conn_girl = json.loads(await ws_girl.recv())
    assert conn_girl["type"] == "connected"
    
    # Boy receives partner_connected
    p_conn = json.loads(await ws_boy.recv())
    assert p_conn["type"] == "partner_connected"
    
    # Register Girl
    await ws_girl.send(json.dumps({"type": "register", "name": "Rose", "role": "girl"}))
    reg_girl = json.loads(await ws_girl.recv())
    assert reg_girl["type"] == "registered"
    print("Girl registered!")

    # Boy receives partner_info (about Girl) and both_ready
    boy_m1 = json.loads(await ws_boy.recv())
    boy_m2 = json.loads(await ws_boy.recv())
    print(f"Boy received: {boy_m1['type']}, {boy_m2['type']}")

    # Girl receives both_ready
    girl_m = json.loads(await ws_girl.recv())
    print(f"Girl received: {girl_m['type']}")
    assert girl_m["type"] == "both_ready"

    print("Both players registered with opposite roles. Server starts rounds!")

    pairs = [
        ("reach_out", "take_hand"),
        ("spin_her", "twirl"),
        ("dip", "lean_back"),
        ("reach_out", "take_hand"),
        ("spin_her", "twirl")
    ]

    for round_idx, (boy_move, girl_move) in enumerate(pairs, start=1):
        # start_round
        sr_boy = json.loads(await ws_boy.recv())
        sr_girl = json.loads(await ws_girl.recv())
        assert sr_boy["type"] == "start_round"
        assert sr_girl["type"] == "start_round"
        round_num = sr_boy["round"]
        print(f"Round {round_num} started by server: 5.0s countdown!")

        # Send dance moves
        await ws_boy.send(json.dumps({"type": "dance_move", "move": boy_move, "round": round_num}))
        await ws_girl.send(json.dumps({"type": "dance_move", "move": girl_move, "round": round_num}))

        # Collect move acks/notifications
        # Boy receives move_locked and partner_moved
        m1 = json.loads(await ws_boy.recv())
        m2 = json.loads(await ws_boy.recv())
        # Girl receives move_locked and partner_moved
        g1 = json.loads(await ws_girl.recv())
        g2 = json.loads(await ws_girl.recv())

        # Then server emits round_success
        res_boy = json.loads(await ws_boy.recv())
        res_girl = json.loads(await ws_girl.recv())
        assert res_boy["type"] == "round_success"
        assert res_girl["type"] == "round_success"
        vibe = res_boy["vibe"]
        print(f"Round {round_num} SUCCESS -> Pair: {res_boy['pair_name']} | New Vibe: {vibe}%")

        if vibe >= 100:
            gw_boy = json.loads(await ws_boy.recv())
            gw_girl = json.loads(await ws_girl.recv())
            assert gw_boy["type"] == "game_win"
            assert gw_girl["type"] == "game_win"
            print("100% Vibe reached! Perfect Sync & game_win broadcasted!")
            break

    # Send letter from Jack to Rose
    letter_text = "Dear Rose,\nSnow falls, music plays, and our steps find each other.\nSincerely,\nJack"
    await ws_boy.send(json.dumps({"type": "send_letter", "text": letter_text}))

    ack = json.loads(await ws_boy.recv())
    assert ack["type"] == "letter_sent_confirm"

    recv = json.loads(await ws_girl.recv())
    assert recv["type"] == "letter_received"
    assert recv["text"] == letter_text
    assert recv["sender"] == "Jack"
    print("Letter successfully received by partner Rose! ✉️")

    await ws_boy.close()
    await ws_girl.close()
    print("\n>>> ALL TESTS PASSED: SYSTEM ROOM, WEBSOCKET SYNC, MOVES, WIN, LETTER <<<")

if __name__ == "__main__":
    asyncio.run(test_full_game_with_system_room())
