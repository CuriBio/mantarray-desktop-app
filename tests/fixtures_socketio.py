# -*- coding: utf-8 -*-

import uuid

import flask_socketio
from flask_socketio import SocketIOTestClient
import pytest
import socketio as python_socketio
from socketio import packet
from socketio.pubsub_manager import PubSubManager


@pytest.fixture(scope="function", name="fsio_test_client_creator")
def fixture_fsio_test_client_creator(mocker):
    class FSIOTestClient(SocketIOTestClient):
        def __init__(self, app, socketio, flask_test_client=None):
            self.app = app
            self.flask_test_client = flask_test_client
            self.eio_sid = uuid.uuid4().hex
            self.acks[self.eio_sid] = None
            self.queue[self.eio_sid] = []
            self.callback_counter = 0
            self.socketio = socketio
            self.connected = {}

            def _mock_send_packet(eio_sid, pkt):
                # make sure the packet can be encoded and decoded
                epkt = pkt.encode()
                if not isinstance(epkt, list):
                    pkt = packet.Packet(encoded_packet=epkt)
                else:
                    pkt = packet.Packet(encoded_packet=epkt[0])
                    for att in epkt[1:]:
                        pkt.add_attachment(att)
                if pkt.packet_type == packet.EVENT or pkt.packet_type == packet.BINARY_EVENT:
                    if eio_sid not in self.queue:
                        self.queue[eio_sid] = []
                    if pkt.data[0] == "message" or pkt.data[0] == "json":
                        self.queue[eio_sid].append(
                            {"name": pkt.data[0], "args": pkt.data[1], "namespace": pkt.namespace or "/"}
                        )
                    else:
                        self.queue[eio_sid].append(
                            {"name": pkt.data[0], "args": pkt.data[1:], "namespace": pkt.namespace or "/"}
                        )
                elif pkt.packet_type == packet.ACK or pkt.packet_type == packet.BINARY_ACK:
                    self.acks[eio_sid] = {"args": pkt.data, "namespace": pkt.namespace or "/"}
                elif pkt.packet_type in [packet.DISCONNECT, packet.CONNECT_ERROR]:
                    self.connected[pkt.namespace or "/"] = False

            self.mock_send_packet = _mock_send_packet

    test_clients = []

    def create_test_client(socketio, flask_app):
        test_client = FSIOTestClient(flask_app, socketio)
        test_clients.append(test_client)

        mocker.patch.object(socketio.server, "_send_packet", side_effect=test_client.mock_send_packet)

        mock_server = python_socketio.Server(**socketio.server_options)
        mocker.patch.object(flask_socketio.socketio, "server", mock_server)
        mock_server.async_handlers = False  # easier to test when
        mock_server.eio.async_handlers = False  # events are sync
        if isinstance(mock_server.manager, PubSubManager):
            raise RuntimeError(
                "Test client cannot be used with a message "
                "queue. Disable the queue on your test "
                "configuration."
            )
        mock_server.manager.initialize()
        mock_server.environ[test_client.eio_sid] = {}

        test_client.connect(namespace=None, query_string=None, headers=None, auth=None)

        return test_client

    yield create_test_client

    for client in test_clients:
        if client.connected:
            client.disconnect()
