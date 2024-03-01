from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.log import setLogLevel
from mininet.cli import CLI


class FatTree(Topo):
    switch_counter = 0
    host_counter = 0

    def __init__(self, k):
        self.k = k
        super().__init__()

    def build(self):
        core_switches = []
        for i in range(self.k):
            core_switches.append(self.__create_switch())

        pods = []
        for i in range(self.k):
            aggregation_switches = []
            for j in range(self.k // 2):
                aggregation_switches.append(self.__create_switch())

            access_switches = []
            for j in range(self.k // 2):
                access_switches.append(self.__create_switch())

            for access_switch in access_switches:
                for aggregation_switch in aggregation_switches:
                    self.addLink(aggregation_switch, access_switch)
                for j in range(self.k // 2):
                    host = self.__create_host()
                    self.addLink(host, access_switch)

            pods.append(aggregation_switches)

        for i in range(self.k):
            for j in range(0, self.k // 2):
                self.addLink(pods[i][0], core_switches[j])
            for j in range(self.k // 2, self.k):
                self.addLink(pods[i][1], core_switches[j])

    def __create_switch(self):
        self.switch_counter += 1
        return self.addSwitch(f's{self.switch_counter}')

    def __create_host(self):
        self.host_counter += 1
        return self.addHost(f'h{self.host_counter}')


def create_fat_tree_topo(k):
    topo = FatTree(k)
    net = Mininet(topo=topo, switch=OVSKernelSwitch, controller=RemoteController)
    net.start()

    for switch in net.switches:
        switch.cmd("ovs-vsctl set Bridge {} protocols=OpenFlow13".format(switch.name))
        switch.cmd("ovs-vsctl set-manager ptcp:6632")

    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    create_fat_tree_topo(4)
