"""Setup script to stitch a link from an OCT FPGA P4 node through the FABRIC OCT-MGHPCC facility port
"""

# Import the Portal object.
import geni.portal as portal
# Import the ProtoGENI library.
import geni.rspec.pg as pg
# We use the URN library below.
import geni.urn as urn
# Emulab extension
import geni.rspec.emulab as emulab
from ipaddress import IPv4Network, IPv6Network


NODE_MIN=1
NODE_MAX=4
VLAN_MIN=3110
VLAN_MAX=3119

# Create a portal context.
pc = portal.Context()

# Create a Request object to start building the RSpec.
request = pc.makeRequestRSpec()

# List of Cloudlab clusters that have Fabric support.
# Limited to "Mass" for this specific profile. Could be expanded in the future.
clusters = [
    ('', 'Select Cluster'),
    ('urn:publicid:IDN+cloudlab.umass.edu+authority+cm', 'Mass')]

# Pick your image.
imageList = [('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD', 'UBUNTU 20.04'),
             ('urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD', 'UBUNTU 22.04')] 

# Pick the appropriate tool version
toolVersion = ['2023.1', '2023.2'] 
                   
pc.defineParameter("nodes","List of nodes",
                   portal.ParameterType.STRING,"",
                   longDescription="Comma-separated list of nodes (e.g., pc151,pc153).")
                   
pc.defineParameter("cluster", "Select Cluster",
                   portal.ParameterType.STRING,
                   clusters[0], clusters,
                   longDescription="Select a cluster")

pc.defineParameter("toolVersion", "Tool Version",
                   portal.ParameterType.STRING,
                   toolVersion[0], toolVersion,
                   longDescription="Select a tool version. It is recommended to use the latest version for the deployment workflow. For more information, visit https://www.xilinx.com/products/boards-and-kits/alveo/u280.html#gettingStarted")
                   
pc.defineParameter("osImage", "Select Image",
                   portal.ParameterType.IMAGE,
                   imageList[0], imageList,
                   longDescription="Supported operating systems are Ubuntu and CentOS.")
                   
# Optional ephemeral blockstore
pc.defineParameter("tempFileSystemSize", "Temporary Filesystem Size",
                   portal.ParameterType.INTEGER, 0,advanced=True,
                   longDescription="The size in GB of a temporary file system to mount on each of your " +
                   "nodes. Temporary means that they are deleted when your experiment is terminated. " +
                   "The images provided by the system have small root partitions, so use this option " +
                   "if you expect you will need more space to build your software packages or store " +
                   "temporary files.")
                   
# Instead of a size, ask for all available space.
pc.defineParameter("tempFileSystemMax",  "Temp Filesystem Max Space",
                    portal.ParameterType.BOOLEAN, False,
                    advanced=True,
                    longDescription="Instead of specifying a size for your temporary filesystem, " +
                    "check this box to allocate all available disk space. Leave the size above as zero.")

pc.defineParameter("tempFileSystemMount", "Temporary Filesystem Mount Point",
                   portal.ParameterType.STRING,"/mydata",advanced=True,
                   longDescription="Mount the temporary file system at this mount point; in general you " +
                   "you do not need to change this, but we provide the option just in case your software " +
                   "is finicky.")
                   
# Retrieve the values the user specifies during instantiation.
params = pc.bindParameters()

# parameterize the vlan to use
portal.context.defineParameter("vlan1", "VLAN1 ID", portal.ParameterType.INTEGER, 3110)
portal.context.defineParameter("vlan2", "VLAN2 ID", portal.ParameterType.INTEGER, 3111)
portal.context.defineParameter("ip_subnet", "IP_SUBNET", portal.ParameterType.STRING, "192.168.1.0/24")
portal.context.defineParameter("node_count", "NODE_COUNT", portal.ParameterType.INTEGER, NODE_MIN)
params = portal.context.bindParameters()

# Check parameter validity.
if params.node_count < NODE_MIN or params.node_count > NODE_MAX:
    portal.context.reportError( portal.ParameterError( "Node count must be between {} and {} inclusive".format(NODE_MIN, NODE_MAX) ) )
    pass

if params.osImage == "urn:publicid:IDN+emulab.net+image+emulab-ops//CENTOS8-64-STD" and params.toolVersion == "2020.1":
    pc.reportError(portal.ParameterError("OS and tool version mismatch.", ["osImage"]))
    pass
    
if params.vlan1 < VLAN_MIN or params.vlan1 > VLAN_MAX:
    portal.context.reportError( portal.ParameterError( "VLAN ID must be in the range {}-{}".format(VLAN_MIN, VLAN_MAX) ) )

if params.vlan2 < VLAN_MIN or params.vlan2 > VLAN_MAX:
    portal.context.reportError( portal.ParameterError( "VLAN ID must be in the range {}-{}".format(VLAN_MIN, VLAN_MAX) ) )

try:
    subnet = IPv4Network(unicode(params.ip_subnet))
except Exception as e:
    try:
        subnet = IPv6Network(unicode(params.ip_subnet))
    except Exception as e:
        raise e
  
pc.verifyParameters()

# Make a LAN
if params.node_count == 1:
    lan1 = request.Link("link", "vlan1")
    lan2 = request.Link("link", "vlan2")
else:
    lan = request.LAN()

interfaces_vlan1 = list()
interfaces_vlan2 = list()

# Request nodes at one of the Utah clusters (Cloudlab Utah, Emulab, APT)
addrs = subnet.hosts()

# Process nodes, adding to FPGA network
nodeList = params.nodes.split(',')
idx = 0
for name in nodeList:
    # Create a node and add it to the request
    node = request.RawPC(name)
    # UMass cluster
    node.component_manager_id = "urn:publicid:IDN+cloudlab.umass.edu+authority+cm"
    # Assign to the node hosting the FPGA.
    node.component_id = name
    node.disk_image = params.osImage
    
    # Optional Blockstore
    if params.tempFileSystemSize > 0 or params.tempFileSystemMax:
        bs = node.Blockstore(name + "-bs", params.tempFileSystemMount)
        if params.tempFileSystemMax:
            bs.size = "0GB"
        else:
            bs.size = str(params.tempFileSystemSize) + "GB"
            pass
        bs.placement = "any"
        pass

    node.addService(pg.Execute(shell="bash", command="sudo /local/repository/post-boot.sh " + params.toolVersion + " >> /local/repository/output_log.txt"))

    # Since we want to create network links to the FPGA, it has its own identity.
    fpga = request.RawPC("fpga-" + name)
    # UMass cluster
    fpga.component_manager_id = "urn:publicid:IDN+cloudlab.umass.edu+authority+cm"
    # Assign to the fgpa node
    fpga.component_id = "fpga-" + name
    # Use the default image for the type of the node selected.
    fpga.setUseTypeDefaultImage()
    
    # Secret sauce.
    fpga.SubNodeOf(node)

    # FPGA interfaces
    #iface1 = fpga.addInterface("if0")
    #iface2 = fpga.addInterface("if1")
    # Must specify the IPv4 address on all stitched links
    #iface1.addAddress(pg.IPv4Address(str(next(addrs)), str(subnet.netmask)))
    #iface2.addAddress(pg.IPv4Address(str(next(addrs)), str(subnet.netmask)))

    iface1 = fpga.addInterface()
    iface1.component_id = "eth0"
    iface1.addAddress(pg.IPv4Address("192.168.1." + str(idx+10), "255.255.255.0"))
    iface2 = fpga.addInterface()
    iface2.component_id = "eth1"
    iface2.addAddress(pg.IPv4Address("192.168.2." + str(idx+10), "255.255.255.0"))

    interfaces_vlan1.append(iface1)
    interfaces_vlan2.append(iface2)

    # Host interfaces
    #iface3 = node.addInterface("if2")
    #iface3.addAddress(pg.IPv4Address(str(next(addrs)), str(subnet.netmask)))
    #interfaces.append(iface3)

    idx = idx + 1
###################################################
# The part below is from Ezra's "stiching" script!

# Request a special node that maps to the scidmz FABRIC port
fabric = request.Node("stitch-node", "emulab-connect")
fabric.Site("stitch")

# Magic.
fabric.component_id = "interconnect-fabric"
# XXX special handling for stitch fabric component_manager_id
if (params.cluster == 'urn:publicid:IDN+cloudlab.umass.edu+authority+cm' or
    params.cluster == 'urn:publicid:IDN+clemson.cloudlab.us+authority+cm'):
    fabric.component_manager_id = params.cluster
else:
    fabric.component_manager_id = "urn:publicid:IDN+cloudlab.umass.edu+authority+cm"
fabric.exclusive = False
siface1 = fabric.addInterface("if0")
siface2 = fabric.addInterface("if1")
# Specify the IPv4 address
siface1.addAddress(pg.IPv4Address("192.168.1." + str(idx+50), "255.255.255.0"))
siface2.addAddress(pg.IPv4Address("192.168.2." + str(idx+50), "255.255.255.0"))
interfaces_vlan1.append(siface1)
interfaces_vlan2.append(siface2)

# Request one of the allowed tags
lan1.setVlanTag(params.vlan1)
lan2.setVlanTag(params.vlan2)

for iface in interfaces_vlan1:
    lan1.addInterface(iface)

for iface in interfaces_vlan2:
    lan2.addInterface(iface)

# Many nodes have a single physical experimental interface, so use
# link multiplexing to make sure it maps to any node.
lan.link_multiplexing = True;

# Use best effort on stitched links.
lan.best_effort = True;

# Print the RSpec to the enclosing page.
pc.printRequestRSpec(request)
